"""Persistent, country-scoped source ID bindings using exact names or dated fixtures."""
from collections import Counter,defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import json

def local_day(stamp,country,zones):
 choices=zones.get(country)
 if isinstance(choices,str):choices=[choices]
 if not choices:raise ValueError('unmapped_physical_venue_timezone:'+str(country))
 d=datetime.fromisoformat(stamp.replace('Z','+00:00'))
 if d.tzinfo is None:raise ValueError('kickoff_timezone_missing')
 days={d.astimezone(ZoneInfo(z)).date() for z in choices}
 if len(days)!=1:raise ValueError('ambiguous_physical_local_date')
 return next(iter(days))

def refresh(source,events,connection):
 import v10_live as live
 connection.execute('CREATE TABLE IF NOT EXISTS identity_bindings(source TEXT PRIMARY KEY,payload TEXT)')
 saved=connection.execute('SELECT payload FROM identity_bindings WHERE source=?',(source['id'],)).fetchone()
 if saved:source.update(json.loads(saved[0]))
 if not source.get('identity_country'):return source
 c=live.duckdb.connect(source['ledger'],read_only=True)
 clubs=live.query(c,'SELECT * FROM clubs WHERE country=?',[source['identity_country']]);byid={x['club']:x for x in clubs}
 bindings=dict(source.get('teams',{}));labels=defaultdict(set)
 for e in events.values():
  for cp in e.get('competitions',[]):
   for t in cp.get('competitors',[]):
    if t.get('team',{}).get('id') and t['team'].get('displayName'):labels[str(t['team']['id'])].add(t['team']['displayName'])
 for pid,names in labels.items():
  if pid in bindings or len(names)!=1:continue
  name=next(iter(names));found=[x for x in clubs if x['name'].casefold()==name.casefold()]
  if len(found)==1:
   x=found[0];bindings[pid]=dict(club=x['club'],country=x['country'],source_label=name,valid_from=source.get('binding_from','2026-01-01'),valid_to='9999-12-31',rule='unique exact country-scoped label',witnesses=[])
 historical=[]
 for e in events.values():
  try:
   cp=e['competitions'][0];s={x['homeAway']:x for x in cp['competitors']};st=(cp.get('status') or e.get('status',{}))['type']
   if len(cp['competitors'])!=2 or st['name']!='STATUS_FULL_TIME' or not st['completed']:continue
   day=local_day(cp['date'],cp.get('venue',{}).get('address',{}).get('country'),source['venue_timezones'])
   historical.append((e['id'],day,{k:str(s[k]['team']['id']) for k in ('home','away')},int(s['home']['score']),int(s['away']['score'])))
  except (KeyError,TypeError,ValueError):continue
 keys=Counter()
 for eid,day,ids,hg,ag in historical:
  if not all(x in bindings for x in ids.values()):continue
  rows=c.execute("SELECT distinct competition_key,competition FROM matches WHERE day=? AND home=? AND away=? AND home_goals=? AND away_goals=? AND kind='league' AND home_tier=? AND away_tier=?",[day,bindings[ids['home']]['club'],bindings[ids['away']]['club'],hg,ag,source['tier'],source['tier']]).fetchall()
  if len(rows)==1:keys[rows[0]]+=1
 if not source.get('competition_key'):
  if not keys or keys.most_common(1)[0][1]<3 or len(keys)!=1:
   c.close();raise ValueError('competition_binding_held:need_three_consistent_historical_fixtures')
  (key,name),_=keys.most_common(1)[0];source.update(competition_key=key,competition=name)
 key=source['competition_key']
 for _ in range(2):
  for pid,names in labels.items():
   if pid in bindings or len(names)!=1:continue
   witnesses=[]
   for eid,day,ids,hg,ag in historical:
    if pid not in ids.values():continue
    side='home' if ids['home']==pid else 'away';other='away' if side=='home' else 'home'
    if ids[other] not in bindings:continue
    rows=c.execute('SELECT match_id,'+side+' FROM matches WHERE day=? AND competition_key=? AND '+other+'=? AND home_goals=? AND away_goals=?',[day,key,bindings[ids[other]]['club'],hg,ag]).fetchall()
    if len(rows)==1 and rows[0][1] in byid:witnesses.append(dict(event_id=eid,date=str(day),match_id=rows[0][0],club=rows[0][1]))
   targets={w['club'] for w in witnesses}
   if len(targets)==1 and len({w['date'] for w in witnesses})>=2:
    club=next(iter(targets));bindings[pid]=dict(club=club,country=byid[club]['country'],source_label=next(iter(names)),valid_from=source.get('binding_from','2026-01-01'),valid_to='9999-12-31',rule='multiple unique dated fixture correspondences',witnesses=witnesses)
 if not source.get('start_after'):source['start_after']=str(c.execute('SELECT max(day) FROM matches WHERE competition_key=?',[key]).fetchone()[0])
 c.close();source['teams']=bindings
 connection.execute('INSERT OR REPLACE INTO identity_bindings VALUES(?,?)',(source['id'],json.dumps({k:source[k] for k in ('teams','start_after','competition','competition_key')})));connection.commit()
 return source
