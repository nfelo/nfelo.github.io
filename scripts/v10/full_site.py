"""Connect the existing NFElo club interface to the live native ledger."""
from collections import Counter,defaultdict
from datetime import date,timedelta
from pathlib import Path
import json,shutil
import v10_live as live
from club_site_export import export_club_site,version_club_assets
from club_model import three_way_probabilities

def verify_export(path,expected):
 index=live.read_json(path/'matches/index.json');clubs=live.read_json(path/'clubs.json')['clubs']
 if sum(r['count'] for r in index['years'])!=expected:raise ValueError('Archive count differs')
 if len({x['code'] for x in clubs})!=len(clubs):raise ValueError('Duplicate club display code')
 for row in index['years']:
  if not (path/'matches'/row['file']).is_file():raise ValueError('Missing match archive')
 for club in clubs:
  if not (path/'club'/(club['code']+'.json')).is_file():raise ValueError('Missing club detail')

def build(input_path,model_path,destination,fixtures,exceptions,health,limitations,as_of,previous=None):
 c=live.duckdb.connect(str(input_path),read_only=True);c.execute("ATTACH '"+str(model_path).replace("'","''")+"' AS model (READ_ONLY)")
 clubs={r['club']:r for r in live.query(c,'SELECT c.*,r.mean,r.rating FROM clubs c JOIN model.current_club_ratings r USING(club)')}
 count,first,last,legs=c.execute('SELECT count(*),min(day),max(day),count(*) FILTER(WHERE leg=2) FROM matches').fetchone()
 source_names=[r[0] for r in c.execute('SELECT distinct source FROM matches').fetchall()];c.close()
 if previous and (previous/'clubs/data/meta.json').exists():shutil.copytree(previous,destination,dirs_exist_ok=True)
 else:
  shutil.copytree(live.HERE/'assets',destination,dirs_exist_ok=True)
  summary=dict(first=str(first),last=str(last),matches=count,raw_matches=count,deduplicated=0,explicit_second_legs=legs,sources=source_names)
  export_club_site(input_path,model_path,live.HERE,live.HERE/'engine',destination,{'sources':[dict(key=h['source'],name=h['source'],status=h['status'],roles=['results','fixtures']) for h in health]},summary,{'metrics':{}},static_verifier=verify_export)
 shutil.copytree(live.HERE/'assets',destination,dirs_exist_ok=True);version_club_assets(destination/'clubs')
 c=live.duckdb.connect(str(input_path),read_only=True);c.execute("ATTACH '"+str(model_path).replace("'","''")+"' AS model (READ_ONLY)")
 data=destination/'clubs/data';config=live.read_json(live.HERE/'engine/club_model.json')
 def compact(row,fixture=False):
  def side(k):
   x=clubs.get(row.get(k),{});return dict(club=x.get('code'),name=x.get('name') or row.get(k+'_name'),association=x.get('country'))
  r=dict(id=str(row.get('match_id') or row.get('id')),date=str(row['day']) if row.get('day') else row.get('date'),home=side('home'),away=side('away'),competition=dict(scope=row.get('competition_key','unresolved'),name=row.get('competition','Unresolved competition'),season=row.get('season'),season_anchor=str(row.get('season','unknown'))),source=dict(key=row.get('source_key') or row.get('source',''),ref=row.get('source_ref','')),round=row.get('round_name',''),leg=row.get('leg'),neutral=row.get('neutral'),lifecycle='fixture' if fixture else row.get('lifecycle','result'),rating_eligible=not fixture and row.get('lifecycle')!='unresolved')
  if row.get('home_goals') is not None:r['score']=dict(displayed=[row['home_goals'],row['away_goals']],model_status=row.get('status'))
  if fixture and row.get('home') in clubs and row.get('away') in clubs:
   h,a=clubs[row['home']],clubs[row['away']];adv=0 if row['neutral'] else config['home_advantage_cross_border' if row['cross_border'] else 'home_advantage_domestic']
   probabilities=three_way_probabilities(h['mean']-a['mean']+adv,config['draw_peak'])
   r['forecast']=dict(probabilities=dict(zip(('home','draw','away'),probabilities)),frozen_after=str(last),method='frozen current underlying means; no future outcomes')
  return r
 recent=[compact(r) for r in live.query(c,'SELECT * FROM matches WHERE day>=? ORDER BY day DESC,match_id',[as_of-timedelta(days=35)])]
 # Past unresolved schedules are never presented as upcoming.
 future=[compact(r,True) for r in fixtures if r.get('date') and r['date']>=str(as_of)]
 held=[]
 for r in exceptions:
  x=dict(r,lifecycle='unresolved',home_name=r.get('home'),away_name=r.get('away'));x.pop('home',None);x.pop('away',None)
  item=compact(x);item['reason']=r['reason'];item['previous_result_retained']=r.get('previous_result_retained',False);held.append(item)
 groups=defaultdict(list)
 for r in future:groups[r['date'][:7]].append(r)
 months=[]
 shutil.rmtree(data/'fixtures',ignore_errors=True)
 for month,rows in sorted(groups.items()):
  rows.sort(key=lambda r:(r['date'],r['id']));live.atomic(data/'fixtures'/(month+'.json'),{'fixtures':rows});months.append(dict(month=month,file=month+'.json',count=len(rows),first=rows[0]['date'],last=rows[-1]['date']))
 live.atomic(data/'fixtures/index.json',dict(months=months,count=len(future),frozen_after=str(last)))
 live.atomic(data/'results/recent.json',dict(results=recent,as_of=str(as_of),window_start=str(as_of-timedelta(days=35))))
 groups=defaultdict(list)
 for r in held:groups[(r.get('date') or 'undated')[:4]].append(r)
 archives=[];shutil.rmtree(data/'unresolved',ignore_errors=True)
 for year,rows in sorted(groups.items()):live.atomic(data/'unresolved'/(year+'.json'),{'observations':rows});archives.append(dict(period=year,file=year+'.json',count=len(rows)))
 live.atomic(data/'unresolved/index.json',dict(count=len(held),reasons=dict(Counter(r['reason'] for r in held)),recent=held[:100],archives=archives,inherited_mixed_identity_matches=259))
 coverage=live.query(c,"SELECT competition_key AS competition_scope,max(competition) AS name,cast(season as varchar) AS season_anchor,count(*) AS results,count(*) AS rated_results,0 AS fixtures,0 AS unresolved,cast(min(day) as varchar) AS earliest_result,cast(max(day) as varchar) AS latest_result,NULL::varchar AS latest_fixture,list(distinct source) AS sources,'historical_snapshot_incomplete' AS coverage_status FROM matches GROUP BY competition_key,season")
 lookup={(r['competition_scope'],r['season_anchor']):r for r in coverage}
 for event in held:
  co=event['competition'];key=(co['scope'],co['season_anchor']);r=lookup.get(key)
  if r is None:
   r=dict(competition_scope=key[0],season_anchor=key[1],name=co['name'],results=0,rated_results=0,fixtures=0,unresolved=0,earliest_result=None,latest_result=None,latest_fixture=None,sources=[],coverage_status='unresolved_observations');coverage.append(r);lookup[key]=r
  r['unresolved']+=1
 for event in future:
  co=event['competition'];key=(co['scope'],co['season_anchor']);r=lookup.get(key)
  if r is None:
   r=dict(competition_scope=key[0],season_anchor=key[1],name=co['name'],results=0,rated_results=0,fixtures=0,unresolved=0,earliest_result=None,latest_result=None,latest_fixture=None,sources=[],coverage_status='automatic_route_partial');coverage.append(r);lookup[key]=r
  r['fixtures']+=1;r['latest_fixture']=max(r['latest_fixture'] or '',event['date']);r['coverage_status']='automatic_route_partial'
 live.atomic(data/'coverage.json',dict(coverage=coverage,statuses=sorted({r['coverage_status'] for r in coverage}),limitations=limitations))
 hrows=[]
 for h in health:
  latest=c.execute("SELECT max(day) FROM matches WHERE source_ref LIKE ?",[h['source']+':%']).fetchone()[0]
  horizon=max([r['date'] for r in future if r['source']['key']==h['source']],default=None)
  hrows.append(dict(source_key=h['source'],source_name=h['source'],authority='ESPN live feed',competition_scope=h['source'],health=h['status'],latest_result=str(latest) if latest else None,result_lag_days=(as_of-latest).days if latest else None,fixture_horizon_days=(date.fromisoformat(horizon)-as_of).days if horizon else None,latest_retrieved_at=h['last_success'],error=h.get('error')))
 live.atomic(data/'source-health.json',dict(source_health=hrows))
 dates={r['date']:r for r in live.query(c,'SELECT cast(day as varchar) date,count(*) results,0 fixtures,0 unresolved FROM matches GROUP BY day ORDER BY day')}
 for kind,rows in [('fixtures',future),('unresolved',held)]:
  for r in rows:
   if r.get('date'):dates.setdefault(r['date'],dict(date=r['date'],results=0,fixtures=0,unresolved=0))[kind]+=1
 live.atomic(data/'indexes/dates.json',{'dates':sorted(dates.values(),key=lambda r:r['date'])});c.close()
 meta=live.read_json(data/'meta.json');meta.update(as_of=str(as_of),completed_results=count,fixtures=len(future),unresolved=len(held),v10_counts=dict(v9_model_contributions_preserved=1626637,v10_net_new_results=count-1626637),coverage_complete=False)
 live.atomic(data/'meta.json',meta)
 bootstrap=live.read_json(data/'bootstrap.json');bootstrap.update(meta=meta,recent_results=recent[:10],upcoming_fixtures=future[:10]);live.atomic(data/'bootstrap.json',bootstrap)
 sources=live.read_json(data/'sources.json');sources['limitations']=limitations;sources['runtime']={'sources':[dict(key=h['source'],name=h['source'],status=h['status'],roles=['results','fixtures']) for h in health]};live.atomic(data/'sources.json',sources)
 live.atomic(data/'publication.json',dict(results=count,fixtures=len(future),unresolved=len(held),clubs=len(clubs),coverage_rows=len(coverage),as_of=str(as_of),global_coverage_accepted=False))
 live.atomic(data/'claims.json',dict(scope='descriptive within documented corpus',global_comparability_established=False,limitations=limitations))
 live.atomic(data/'records-evidence.json',dict(source='frozen native model',model_sha256=live.file_sha(model_path),global_comparability_established=False))
 live.atomic(destination/'index.html',b'<!doctype html><meta http-equiv="refresh" content="0;url=clubs/"><a href="clubs/">NFElo Clubs</a>')
 return meta
