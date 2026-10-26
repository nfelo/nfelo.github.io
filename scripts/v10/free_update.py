"""Persistent wider-source scheduler used by the actual club updater."""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import v10_live as live
from free_sources import FOTMOB,ESPN,fotmob,load_route
from club_identity import Resolver
from source_registry import from_catalogue

def collect(root,config,as_of,fetcher=None,bootstrap=True):
 c=live.state_db(root);f=fetcher or live.Fetcher(root,c,config.get('http_timeout',20));health=[];batches=[]
 c.executescript('CREATE TABLE IF NOT EXISTS source_fetch_reports(source TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS raw_routes(source TEXT PRIMARY KEY,payload TEXT,checked_at TEXT); CREATE TABLE IF NOT EXISTS source_catalogue(id TEXT PRIMARY KEY,payload TEXT,checked_at TEXT);')
 sources=[dict(x) for x in config['sources']];clock=datetime.now(timezone.utc)
 # Discovery runs weekly. Existing reviewed competition scope is preserved;
 # new unsupported types stay outside the enabled set.
 if config.get('discover',True):
  saved=c.execute("SELECT payload,checked_at FROM source_catalogue WHERE id='fotmob'").fetchone()
  try:
   if not saved or (clock-datetime.fromisoformat(saved[1])).days>=config.get('discovery_days',7):
    catalogue=f.get(FOTMOB+'/allLeagues');c.execute('INSERT OR REPLACE INTO source_catalogue VALUES(?,?,?)',('fotmob',json.dumps(catalogue),clock.isoformat()));c.commit()
   else:catalogue=json.loads(saved[0])
   known={x['id'] for x in sources}
   sources += [x for x in from_catalogue(catalogue) if x['id'] not in known]
  except Exception as e:health.append(dict(source='fotmob-catalogue',status='stale' if saved else 'unavailable',error=str(e)))
 due=[]
 parser_sha=live.file_sha(live.HERE/'free_sources.py')+live.file_sha(live.HERE/'wider_sources.py')
 for s in sources:
  saved=c.execute('SELECT payload,checked_at FROM raw_routes WHERE source=?',(s['id'],)).fetchone()
  parser=c.execute('SELECT payload FROM source_catalogue WHERE id=?',(s['id']+'-parser',)).fetchone()
  refresh=not saved or not parser or parser[0]!=parser_sha or (clock-datetime.fromisoformat(saved[1])).total_seconds()>=3600*s.get('refresh_hours',20)
  due.append((s,saved,refresh))
 if fetcher is None:
  urls=[FOTMOB+'/leagues?id='+s['provider_id'] if s['provider']=='fotmob' else ESPN+'/'+s['provider_id']+'/scoreboard?dates='+str(as_of.year)+'&limit=1000' for s,_,refresh in due if refresh and s['provider'] in ('fotmob','espn')]
  f.prefetch(urls,workers=4)
 for s,saved,refresh in due:
  old=json.loads(saved[0]) if saved else None
  try:
   if refresh:
    boot=c.execute('SELECT payload FROM source_catalogue WHERE id=?',(s['id']+'-bootstrap',)).fetchone()
    if s['provider']=='gsa':
     from wider_sources import collect_gsa
     rows=collect_gsa(s,f,as_of,c,old or [])
    else:rows=load_route(s,f,as_of,bootstrap=bootstrap and (not boot or boot[0]!=str(as_of.year)))
    if not s.get('_warnings'):c.execute('INSERT OR REPLACE INTO source_catalogue VALUES(?,?,?)',(s['id']+'-bootstrap',str(as_of.year),clock.isoformat()))
    # Seasons roll over: a smaller current season is legitimate. Only compare
    # a like-for-like season snapshot; never erase omitted observations.
    if old and rows and {r.get('season') for r in rows}=={r.get('season') for r in old} and len(rows)<len(old)*.5:raise ValueError('unexpected_source_contraction')
    c.execute('INSERT OR REPLACE INTO raw_routes VALUES(?,?,?)',(s['id'],json.dumps(rows),clock.isoformat()));c.execute('INSERT OR REPLACE INTO source_catalogue VALUES(?,?,?)',(s['id']+'-parser',parser_sha,clock.isoformat()));c.commit()
    c.execute('INSERT OR REPLACE INTO source_fetch_reports VALUES(?,?)',(s['id'],json.dumps({'_warnings':s.get('_warnings',[]),'_backfill':s.get('_backfill')})));c.commit()
   else:
    rows=old
    report=c.execute('SELECT payload FROM source_fetch_reports WHERE source=?',(s['id'],)).fetchone()
    if report:s.update(json.loads(report[0]))
   health.append(dict(source=s['id'],status='retrieved' if refresh else 'cached',rows=len(rows),last_success=clock.isoformat() if refresh else saved[1],archive_warnings=s.get('_warnings',[]),backfill=s.get('_backfill')))
  except Exception as e:
   rows=old or [];health.append(dict(source=s['id'],status='stale' if saved else 'unavailable',rows=len(rows),last_success=saved[1] if saved else None,error=str(e)))
  batches.append((s,rows))
 # A small dated feed updates active FotMob competitions between season scans.
 # Carry the cached season and bracket context forward for daily observations.
 if config.get('daily',True):
  by_id={str(s['provider_id']):(s,rows) for s,rows in batches if s['provider']=='fotmob'}
  for offset in range(-config.get('daily_lookback_days',3),2):
   day=as_of+timedelta(days=offset)
   try:
    payload=f.get(FOTMOB+'/matches?date='+day.strftime('%Y%m%d'))
    if not isinstance(payload.get('leagues'),list):raise ValueError('daily_schema_changed')
    for league in payload['leagues']:
     pair=by_id.get(str(league.get('primaryId') or league.get('id')))
     if not pair:continue
     s,rows=pair;known={r['id']:r for r in rows};season=max((r.get('season') or as_of.year for r in rows),default=as_of.year)
     matches=[dict(m,roundName=m.get('tournamentStage','')) for m in league.get('matches',[])]
     fresh=fotmob({'details':{'id':s['provider_id'],'gender':'male','name':s['competition'],'selectedSeason':str(season)},'fixtures':{'allMatches':matches}},s)
     for r in fresh:
      old=known.get(r['id'],{})
      for k in ('season','season_label','leg','tie_round','round_name','aggregate_before_home','aggregate_after_home'):
       if old.get(k) is not None:r[k]=old[k]
      known[r['id']]=r
     rows[:]=list(known.values())
   except Exception as e:health.append(dict(source='fotmob-daily-'+str(day),status='unavailable',error=str(e)))
 resolver=Resolver(root/live.read_json(root/'current.json')['input'],c)
 try:
  resolver.prepare(batches,as_of)
  live.atomic(root/'pending_clubs.json',[r for club,r in sorted(resolver.clubs.items()) if club not in resolver.original_ids])
  for s,rows in batches:
   result=[]
   for raw in rows:
    r=resolver.convert(s,raw,as_of)
    # Retain historical results for corrections, but don't export distant
    # future fixture lists or year-old postponed schedules as upcoming.
    if r.get('date') and r['date']>str(as_of+timedelta(days=35)):continue
    result.append(r);p=live.encoded(r);c.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?)',(s['id'],r['id'],p.decode(),live.digest(p),live.now()))
   h=next(x for x in health if x['source']==s['id']);h['normalised_results']=sum(r['lifecycle']=='result' for r in result);h['held']=sum(r['lifecycle']=='unresolved' for r in result)
   h['latest_result']=max((r['date'] for r in result if r['lifecycle']=='result'),default=None)
   h['next_fixture']=min((r['date'] for r in result if r['lifecycle']=='fixture' and r.get('date') and r['date']>=str(as_of)),default=None)
   if h['status'] in ('retrieved','cached'):h['status']='partial' if h['held'] or h.get('archive_warnings') else 'healthy' if result else 'empty'
  c.commit()
  enabled={s['id'] for s,_ in batches}
  obs=[(sid,json.loads(p)) for sid,p in c.execute('SELECT source,payload FROM observations ORDER BY source,event_id') if sid in enabled]
  return obs,health,{'http_requests':f.requests,'unchanged_responses':f.unchanged}
 finally:resolver.close();c.close()
