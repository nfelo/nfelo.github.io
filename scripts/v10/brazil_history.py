"""Idempotent historical supplement, keyed by stable club codes."""
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path
import hashlib,json
def load_history():
 root=Path(__file__).parent;raw=(root/'brazil_history.json').read_bytes();expected=json.loads((root/'engine/club_model.json').read_text()).get('brazil_history_sha256')
 if expected and hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Historical Brazil checksum differs')
 return json.loads(raw)
def apply_history(connection,payload=None):
 if payload is None:payload=load_history()
 fields=[x[0] for x in connection.execute('DESCRIBE clubs').fetchall()]
 catalog={r[fields.index('code')]:dict(zip(fields,r)) for r in connection.execute('SELECT * FROM clubs').fetchall()}
 next_club=max((r['club'] for r in catalog.values()),default=-1)+1;bindings={};held=[];new=[]
 for spec in payload['clubs']:
  code=spec['code'];old=catalog.get(code)
  if old:
   if old['name']!=spec['name'] or old['country']!='brazil':held.append({'code':code,'reason':'historical_club_precondition_changed'});continue
   bindings[code]=old['club']
  elif spec['existing']:held.append({'code':code,'reason':'historical_club_missing'})
  else:
   if any(r['country']=='brazil' and r['name']==spec['name'] for r in catalog.values()):held.append({'code':code,'reason':'historical_club_name_already_present'});continue
   new.append(dict(club=next_club,code=code,name=spec['name'],country='brazil',country_name='Brazil',country_code='BR',continent='South America',identity='rsssf-brasil:'+code,resolution='reviewed state-scoped historical identity'))
   bindings[code]=next_club;next_club+=1
 match_fields=[x[0] for x in connection.execute('DESCRIBE matches').fetchall()];minimum=min(r['date'] for r in payload['matches']);maximum=max(r['date'] for r in payload['matches'])
 pairs=defaultdict(list);busy=defaultdict(set);ids=set()
 stored=connection.execute('SELECT match_id,day,home,away,home_goals,away_goals FROM matches WHERE day BETWEEN ? AND ?',[date.fromisoformat(minimum)-timedelta(days=1),date.fromisoformat(maximum)+timedelta(days=1)]).fetchall()
 for mid,day,home,away,hg,ag in stored:ids.add(mid);pairs[day,frozenset((home,away))].append((home,away,hg,ag));busy[day].update((home,away))
 prepared=[]
 for r in payload['matches']:
  home,away=bindings.get(r['home_code']),bindings.get(r['away_code'])
  if home is None or away is None:held.append(dict(r,reason='unresolved_historical_identity'));continue
  prepared.append((r,date.fromisoformat(r['date']),home,away))
 candidates=defaultdict(set);participants=defaultdict(set)
 for r,day,h,a in prepared:candidates[day,frozenset((h,a))].add((h,a,r['home_goals'],r['away_goals']));participants[day,h].add(a);participants[day,a].add(h)
 counts=dict(added=0,already_present=0,new_clubs=0,held=held);inserts=[];new_used=set()
 for r,day,home,away in sorted(prepared,key=lambda x:(x[1],x[0]['match_id'])):
  key=day,frozenset((home,away))
  if r['match_id'] in ids:counts['already_present']+=1;continue
  if len(candidates[key])>1:held.append(dict(r,reason='historical_source_score_conflict'));continue
  if len(participants[day,home])>1 or len(participants[day,away])>1:held.append(dict(r,reason='historical_multiple_opponents_same_day'));continue
  same=False;conflict=False
  for offset in (-1,0,1):
   for h,a,hg,ag in pairs[day+timedelta(days=offset),key[1]]:
    if h!=home:hg,ag=ag,hg
    if (hg,ag)==(r['home_goals'],r['away_goals']):same=True
    elif offset==0:conflict=True
  if same:counts['already_present']+=1;continue
  if conflict or {home,away}&busy[day]:held.append(dict(r,reason='historical_same_day_conflict'));continue
  row=dict(match_id=r['match_id'],day=day,season=r['season'],home=home,away=away,home_goals=r['home_goals'],away_goals=r['away_goals'],competition=r['competition'],competition_key='rsssf-brasil:'+r['scope'].lower()+':'+('taca-brasil' if r['kind']=='domestic_cup' else 'robertao' if 'Pedrosa' in r['competition'] else 'league'),kind=r['kind'],home_tier=1,away_tier=1,neutral=r['neutral'],cross_border=False,status=r['status'],leg=0,tie_key=None,round_name='',source='rsssf-brasil',source_ref=r['source_ref'],aggregate_before_home=None,aggregate_after_home=None)
  inserts.append([row[k] for k in match_fields]);ids.add(r['match_id']);busy[day].update((home,away));pairs[key].append((home,away,r['home_goals'],r['away_goals']));new_used.update((home,away))
 for club in new:
  if club['club'] not in new_used:continue
  actual=max((x['club'] for x in catalog.values()),default=-1)+1;proposed=club['club'];club['club']=actual
  for row in inserts:
   for side in ('home','away'):
    p=match_fields.index(side)
    if row[p]==proposed:row[p]=actual
  connection.execute('INSERT INTO clubs VALUES('+','.join('?' for _ in fields)+')',[club[k] for k in fields]);catalog[club['code']]=club;counts['new_clubs']+=1
 if inserts:connection.executemany('INSERT INTO matches VALUES('+','.join('?' for _ in match_fields)+')',inserts)
 counts['added']=len(inserts);return counts
