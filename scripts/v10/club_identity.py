"""Persistent provider IDs with country-scoped labels and dated-match witnesses.

No fuzzy auto-merges and no date-of-last-result cutoff. An unresolved team holds
its own observations, not every other match in that competition.
"""
from bisect import bisect_right
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json,re,unicodedata
from difflib import SequenceMatcher
from free_sources import eligible
import v10_live as live

def norm(text):
 text=unicodedata.normalize('NFKD',text or '').encode('ascii','ignore').decode().lower()
 words=re.findall(r'[a-z0-9]+',text)
 return ' '.join(x for x in words if x not in ('fc','cf','afc','sc','fk','sk','ac','as','cd','club','football','futbol'))

class Resolver:
 def __init__(self,ledger,connection):
  self.db=connection;self.c=live.duckdb.connect(str(ledger),read_only=True)
  self.clubs={r['club']:r for r in live.query(self.c,'SELECT * FROM clubs')};self.original_ids=set(self.clubs)
  connection.execute('CREATE TABLE IF NOT EXISTS new_provider_clubs(club INTEGER PRIMARY KEY,payload TEXT)')
  for club,payload in connection.execute('SELECT * FROM new_provider_clubs'):
   if club not in self.clubs:self.clubs[club]=json.loads(payload)
  self.countries={norm(r['country_name']):r['country'] for r in self.clubs.values()}
  self.countries.update({norm(r['country']):r['country'] for r in self.clubs.values()})
  for alias,old in [('Turkiye','Turkey'),('Czechia','Czech Republic'),('Bosnia-Herzegovina','Bosnia and Herzegovina'),('United States','USA'),('North Macedonia','Macedonia')]:
   if norm(old) in self.countries:self.countries[norm(alias)]=self.countries[norm(old)]
  self.names=defaultdict(set)
  for r in self.clubs.values():self.names[r['country'],norm(r['name'])].add(r['club'])
  self.bindings={};self.competitions={};self.witnesses=defaultdict(list)
  connection.execute('CREATE TABLE IF NOT EXISTS provider_clubs(provider TEXT,id TEXT,club INTEGER,label TEXT,evidence TEXT,PRIMARY KEY(provider,id))')
  connection.execute('CREATE TABLE IF NOT EXISTS provider_competitions(source TEXT PRIMARY KEY,payload TEXT)')
  for provider,pid,club,label,evidence in connection.execute('SELECT * FROM provider_clubs'):
   if club in self.clubs:self.bindings[provider,pid]=club
  for sid,payload in connection.execute('SELECT * FROM provider_competitions'):self.competitions[sid]=json.loads(payload)
  # Reuse the previous live updater's already evidenced ESPN identities.
  exists=connection.execute("SELECT 1 FROM sqlite_master WHERE name='identity_bindings'").fetchone()
  if exists:
   for _,payload in connection.execute('SELECT * FROM identity_bindings'):
    for pid,b in json.loads(payload).get('teams',{}).items():
     if b['club'] in self.clubs:self.bindings['espn',str(pid)]=b['club']
  self.by_date=defaultdict(list);self.witness_date=defaultdict(list);self.by_pair=defaultdict(list);self.tiers=defaultdict(list)
  for r in live.query(self.c,"SELECT * FROM matches WHERE day>=DATE '2023-01-01' ORDER BY day,match_id"):
   self.by_date[str(r['day'])].append(r);self.by_pair[r['home'],r['away']].append(r)
   if r['kind']=='league':
    for side in ('home','away'):self.tiers[r[side]].append((r['day'],r[side+'_tier']))
  self.zones=defaultdict(list)
  zonefile=Path('/usr/share/zoneinfo/zone.tab')
  if zonefile.exists():
   for line in zonefile.read_text().splitlines():
    if line and not line.startswith('#'):
     cols=line.split('\t');self.zones[cols[0]].append(cols[2])
  self.zones.update({x:['Europe/London'] for x in ('EN','ENG','SC','SCO','SQ','WA','WAL','NI','NIR','EI','GB')})
  self.zones.update({'XK':['Europe/Belgrade'],'PS':['Asia/Hebron']})
  self.country_zones={country:sorted({z for r in self.clubs.values() if r['country']==country for z in self.zones.get(r['country_code'],[])}) for country in {r['country'] for r in self.clubs.values()}}
 def close(self):self.db.commit();self.c.close()
 def bind(self,provider,pid,club,label,evidence):
  if (provider,pid) in self.bindings and self.bindings[provider,pid]!=club:raise ValueError('provider_identity_conflict')
  self.bindings[provider,pid]=club;self.db.execute('INSERT OR REPLACE INTO provider_clubs VALUES(?,?,?,?,?)',(provider,pid,club,label,json.dumps(evidence)))
 def near(self,r,witness=False):
  stamp=(r.get('kickoff') or r.get('date') or '')[:10]
  try:day=date.fromisoformat(stamp)
  except (ValueError,TypeError):return []
  rows=[m for offset in (-1,0,1) for m in self.by_date[str(day+timedelta(days=offset))]+(self.witness_date[str(day+timedelta(days=offset))] if witness else []) if m['home_goals']==r.get('home_goals') and m['away_goals']==r.get('away_goals')]
  return list({(m['day'],m['home'],m['away']):m for m in rows}.values())
 def prepare(self,batches,as_of=None):
  as_of=as_of or date.today()
  for source,rows in batches:
   provider=source['provider'];country=self.countries.get(norm(source.get('country')))
   for r in rows:
    for side in ('home','away'):
     pid=str(r.get(side+'_id') or '');name=r.get(side+'_name')
     if not pid or (provider,pid) in self.bindings or not country:continue
     found=self.names[country,norm(name)]
     if len(found)==1:self.bind(provider,pid,next(iter(found)),name,{'rule':'unique_normalised_country_label'})
  # Two independent dated fixtures connect spelling variants and foreign clubs
  # in a domestic league. A lone matching score can never merge identities.
  for _ in range(3):
   changed=0
   self.witness_date.clear()
   for source,rows in batches:
    for r in rows:
     if r.get('lifecycle')!='result' or source['kind']!='league':continue
     h=self.bindings.get((source['provider'],str(r.get('home_id'))));a=self.bindings.get((source['provider'],str(r.get('away_id'))))
     if h is None or a is None:continue
     try:day=self.local_day(r,source,h)
     except (ValueError,KeyError,TypeError):continue
     self.witness_date[str(day)].append(dict(day=day,home=h,away=a,home_goals=r['home_goals'],away_goals=r['away_goals']))
   for source,rows in batches:
    provider=source['provider'];country=self.countries.get(norm(source.get('country')))
    evidence=defaultdict(list)
    for r in rows:
     if r.get('lifecycle')!='result':continue
     for side,other in [('home','away'),('away','home')]:
      pid=str(r.get(side+'_id') or '');known=self.bindings.get((provider,str(r.get(other+'_id'))))
      if not pid or (provider,pid) in self.bindings or known is None:continue
      matches=[m for m in self.near(r,True) if m[other]==known and (not country or self.clubs[m[side]]['country']==country)]
      if len(matches)==1:evidence[pid].append((matches[0][side],str(matches[0]['day']),r[side+'_name']))
    for pid,witness in evidence.items():
     targets={x[0] for x in witness}
     if len(targets)==1 and len({x[1] for x in witness})>=2:
      self.bind(provider,pid,next(iter(targets)),witness[0][2],{'rule':'multiple_dated_fixtures','witnesses':witness});changed+=1
   if not changed:break
  # A new senior-league member may be admitted from repeated completed games
  # against resolved opponents. Possible aliases remain held, never duplicated.
  for source,rows in batches:
   country=self.countries.get(norm(source.get('country')));provider=source['provider']
   if source['kind']!='league' or not country or not source.get('tier'):continue
   candidates=defaultdict(list)
   for r in rows:
    if r.get('lifecycle')!='result' or (r.get('kickoff') or r.get('date') or '')[:10]>as_of.isoformat():continue
    for side,other in [('home','away'),('away','home')]:
     pid=str(r.get(side+'_id') or '');label=r.get(side+'_name') or ''
     if pid and (provider,pid) not in self.bindings and (provider,str(r.get(other+'_id'))) in self.bindings and eligible(label):candidates[pid].append((label,(r.get('kickoff') or r.get('date') or '')[:10],str(r.get(other+'_id'))))
   for pid,records in candidates.items():
    labels={norm(r[0]) for r in records};days={r[1] for r in records};opponents={r[2] for r in records}
    if len(labels)!=1 or len(days)<2 or len(opponents)<2:continue
    label=records[0][0];normal=norm(label)
    names=[(n,ids) for (co,n),ids in self.names.items() if co==country and ids]
    exact=self.names.get((country,normal),set())
    if len(exact)==1:
     self.bind(provider,pid,next(iter(exact)),label,{'rule':'unique_normalised_country_label'});continue
    # Any historical fixture with the same known opponent could be an alias.
    possible_alias=False
    for raw in rows:
     for side,other in [('home','away'),('away','home')]:
      if str(raw.get(side+'_id'))!=pid:continue
      known=self.bindings.get((provider,str(raw.get(other+'_id'))))
      if known is not None and any(m[other]==known for m in self.near(raw)):possible_alias=True
    if possible_alias:continue
    if not normal or any(SequenceMatcher(None,normal,n).ratio()>=.68 or set(normal.split())<=set(n.split()) or set(n.split())<=set(normal.split()) for n,_ in names if n):continue
    meta=next(x for x in self.clubs.values() if x['country']==country);club=max(self.clubs)+1;code='p'+live.digest((provider+':'+pid).encode())[:11]
    row={k:v for k,v in meta.items()};row.update(club=club,code=code,name=label,identity=provider+':'+pid,resolution='provider_member_with_dated_opponents')
    self.clubs[club]=row;self.names[country,normal].add(club);self.db.execute('INSERT INTO new_provider_clubs VALUES(?,?)',(club,json.dumps(row)));self.bind(provider,pid,club,label,{'rule':'new_league_member','source':source['id'],'witnesses':records})
  for source,rows in batches:
   votes=Counter();provider=source['provider']
   for r in rows:
    h=self.bindings.get((provider,str(r.get('home_id'))));a=self.bindings.get((provider,str(r.get('away_id'))))
    matches=[m for m in self.near(r) if m['home']==h and m['away']==a and m['kind']==source['kind']]
    if len(matches)==1:votes[matches[0]['competition_key']]+=1
   saved=self.competitions.get(source['id'])
   if saved:source.update(saved)
   elif votes:
    key,count=votes.most_common(1)[0]
    if count>=3 and count/sum(votes.values())>=.8:
     source['competition_key']=key;self.competitions[source['id']]={'competition_key':key};self.db.execute('INSERT OR REPLACE INTO provider_competitions VALUES(?,?)',(source['id'],json.dumps(self.competitions[source['id']])))
   source.setdefault('competition_key','public:'+source['id'])
   if source['kind']=='league' and source.get('tier'):
    for r in rows:
     for side in ('home','away'):
      club=self.bindings.get((provider,str(r.get(side+'_id'))))
      if club is None:continue
      try:day=date.fromisoformat((r.get('kickoff') or r.get('date') or '')[:10])
      except ValueError:continue
      self.tiers[club].append((day,source['tier']))
  for club in self.tiers:self.tiers[club]=sorted(set(self.tiers[club]))
  # Reuse explicit leg/venue facts from an agreeing independent observation.
  facts=defaultdict(list)
  for source,rows in batches:
   for r in rows:
    h=self.bindings.get((source['provider'],str(r.get('home_id'))));a=self.bindings.get((source['provider'],str(r.get('away_id'))))
    if h is None or a is None or r.get('lifecycle')!='result':continue
    try:day=self.local_day(r,source,h)
    except (ValueError,KeyError,TypeError):continue
    facts[day,h,a,r.get('home_goals'),r.get('away_goals'),r.get('status')].append(r)
  for records in facts.values():
   explicit=[r for r in records if r.get('leg') is not None]
   signatures={(r.get('leg'),r.get('aggregate_before_home'),r.get('aggregate_after_home')) for r in explicit}
   if len(signatures)==1 and explicit:
    for r in records:
     if r.get('leg') is None:
      for k in ('leg','aggregate_before_home','aggregate_after_home','tie_round'):r[k]=explicit[0].get(k)
   countries={r.get('venue_country') for r in records if r.get('venue_country')}
   if len(countries)==1:
    for r in records:
     if not r.get('venue_country'):r['venue_country']=next(iter(countries))
  self.db.commit()
 def local_day(self,r,source,home):
  if r.get('date_basis')=='provider_local_date':return date.fromisoformat(r['date'])
  dt=datetime.fromisoformat(r['kickoff'].replace('Z','+00:00'))
  if dt.tzinfo is None:raise ValueError('kickoff_timezone_missing')
  country=self.countries.get(norm(r.get('venue_country'))) or self.clubs[home]['country']
  zones=source.get('timezones') or self.country_zones.get(country,[])
  if not zones:raise ValueError('unknown_venue_timezone:'+str(country))
  days={dt.astimezone(ZoneInfo(z)).date() for z in zones}
  if len(days)!=1:raise ValueError('ambiguous_physical_local_date')
  return next(iter(days))
 def tier(self,club,day,source):
  if source['kind']=='league' and source.get('tier'):return source['tier']
  history=self.tiers.get(club,[]);index=bisect_right(history,(day,100))-1
  if index>=0:return history[index][1]
  raise ValueError('unknown_current_tier')
 def convert(self,source,r,as_of):
  out=dict(r,competition=source['competition'],competition_key=source['competition_key'],kind=source['kind'],date=(r.get('kickoff') or r.get('date') or '')[:10])
  try:
   if r.get('lifecycle')=='unresolved':raise ValueError(';'.join(r.get('reasons',[])))
   for side in ('home','away'):
    club=self.bindings.get((source['provider'],str(r.get(side+'_id'))))
    if club is None:raise ValueError('unknown_'+side+'_identity:'+str(r.get(side+'_id')))
    out[side]=club
   existing=[m for m in self.near(r) if m['home']==out['home'] and m['away']==out['away'] and m['kind']==source['kind']]
   day=existing[0]['day'] if len(existing)==1 else self.local_day(r,source,out['home'])
   if r['lifecycle']=='result' and day>as_of:raise ValueError('future_completed_result')
   out.update(date=str(day),cross_border=self.clubs[out['home']]['country']!=self.clubs[out['away']]['country'])
   for side in ('home','away'):out[side+'_tier']=self.tier(out[side],day,source)
   if len(existing)==1:
    for field in ('competition_key','competition','neutral','leg','tie_key','round_name','aggregate_before_home','aggregate_after_home'):out[field]=existing[0][field]
   else:
    final=bool(re.fullmatch(r'final',r.get('round_name',''),re.I))
    out['neutral']=bool(source.get('neutral_all') or (source.get('neutral_final') and final) or r.get('neutral'))
    out['venue_basis']='competition_neutral_rule' if source.get('neutral_all') or (source.get('neutral_final') and final) else 'provider_flag' if type(r.get('neutral')) is bool else 'listed_home_ground_assumption'
    # A league round is single-legged. Cup phases require a bracket or an
    # explicit source leg, so a second leg is never silently weighted as one.
    leg=r.get('leg')
    if leg is None:
     if source['kind']=='league' or r.get('round_name','').isdigit() or re.search('group|league phase|league stage',r.get('round_name',''),re.I) or final:leg=0
     else:raise ValueError('knockout_leg_context_missing')
    out.update(leg=leg,tie_key=None,aggregate_before_home=r.get('aggregate_before_home'),aggregate_after_home=r.get('aggregate_after_home'))
    if leg:
     out['tie_key']=':'.join([source['competition_key'],str(r['season']),(r.get('tie_round') or r.get('round_name') or ''),str(min(out['home'],out['away'])),str(max(out['home'],out['away']))])
    if out['neutral'] and not source.get('timezones') and not r.get('venue_country'):raise ValueError('neutral_venue_country_missing')
   out['evidence']={'provider':source['provider'],'provider_event':r['id'],'score_excludes_shootout':True,'venue_basis':out.get('venue_basis','existing_verified_ledger'),'raw_status':r.get('raw_status')}
  except (ValueError,KeyError,TypeError) as e:out.update(lifecycle='unresolved',reasons=[str(e)])
  return out
