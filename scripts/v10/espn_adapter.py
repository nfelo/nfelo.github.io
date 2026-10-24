"""Current-season ESPN league adapter with explicit venue and identity fields."""
from datetime import datetime,timedelta
import json,re,urllib.error
from zoneinfo import ZoneInfo

def collect_espn(source,fetcher,connection,as_of):
 from v10_live import digest,encoded,now
 slug=source['league'];base=source.get('base_url','https://site.api.espn.com/apis/site/v2/sports/soccer')
 prior=connection.execute('SELECT cursor FROM sources WHERE id=?',(source['id'],)).fetchone()
 first=int(source.get('start_after',source.get('binding_from','2026-01-01'))[:4])
 if prior and prior[0]:first=max(first,as_of.year-1,int(prior[0][:4]))
 events={}
 for year in range(first,as_of.year+1):
  payload=fetcher.get(f'{base}/{slug}/scoreboard?dates={year}&limit=1000')
  if not isinstance(payload,dict) or not isinstance(payload.get('events'),list):raise ValueError('Scoreboard schema changed')
  leagues=payload.get('leagues') or []
  if leagues and not any(x.get('slug')==slug or x.get('abbreviation')==slug for x in leagues):raise ValueError('Wrong competition returned')
  rows=payload['events']
  if len(rows)>=1000:
   parent_ids={str(x['id']) for x in rows};rows=[]
   for month in range(1,13):
    p=fetcher.get(f'{base}/{slug}/scoreboard?dates={year}{month:02d}&limit=1000')
    if not isinstance(p.get('events'),list) or len(p['events'])>=1000:raise ValueError('Monthly source incomplete')
    rows.extend(p['events'])
   if not parent_ids<={str(x['id']) for x in rows}:raise ValueError('Pagination lost events')
  for e in rows:
   eid=str(e.get('id') or '')
   if not eid:raise ValueError('Missing source event ID')
   if eid in events and encoded(events[eid])!=encoded(e):raise ValueError('Conflicting repeated source event')
   events[eid]=e
 from identity_refresh import refresh,local_day
 source=refresh(source,events,connection)
 pending=[]
 for eid,event in sorted(events.items()):
  stamp=event.get('date','')[:10]
  if stamp<=source['start_after'] or stamp>(as_of+timedelta(days=source.get('fixture_days',35))).isoformat():continue
  saved=connection.execute('SELECT signature,checked_at FROM summaries WHERE source=? AND event_id=?',(source['id'],eid)).fetchone()
  signature=event_signature(event)
  recent=stamp>=(as_of-timedelta(days=source.get('correction_days',14))).isoformat()
  cs=event.get('competitions',[{}])[0].get('competitors',[])
  if all(str(t.get('team',{}).get('id')) in source['teams'] for t in cs) and (not saved or saved[0]!=signature or (recent and saved[1][:10]!=as_of.isoformat())):pending.append(f'{base}/{slug}/summary?event={eid}')
 fetcher.prefetch(pending,workers=source.get('fetch_workers',6))
 output=[]
 for eid,event in sorted(events.items()):
  stamp=event.get('date','')[:10]
  if stamp<=source['start_after']:continue
  if stamp>(as_of+timedelta(days=source.get('fixture_days',35))).isoformat():continue
  row=dict(id=eid,date=stamp or None,lifecycle='unresolved',reasons=[],provider='espn',league=slug)
  try:
   if len(event.get('competitions',[]))!=1:raise ValueError('competition_count')
   c=event['competitions'][0];sides={t.get('homeAway'):t for t in c.get('competitors',[])}
   if len(c['competitors'])!=2 or set(sides)!={'home','away'}:raise ValueError('unordered_competitors')
   bindings={}
   for side in ('home','away'):
    team=sides[side]['team'];pid=str(team['id']);row[side+'_name']=team.get('displayName')
    binding=source['teams'].get(pid)
    if not binding:raise ValueError('unknown_'+side+'_identity:'+pid)
    if binding.get('source_label') and binding['source_label']!=team.get('displayName'):raise ValueError('changed_'+side+'_identity_label:'+pid)
    if not binding['valid_from']<=stamp<=binding['valid_to']:raise ValueError('expired_'+side+'_identity:'+pid)
    row[side]=int(binding['club']);bindings[side]=binding
   signature=event_signature(event)
   saved=connection.execute('SELECT signature,payload,checked_at FROM summaries WHERE source=? AND event_id=?',(source['id'],eid)).fetchone()
   recent=stamp>=(as_of-timedelta(days=source.get('correction_days',14))).isoformat()
   if saved and saved[0]==signature and (not recent or saved[2][:10]==as_of.isoformat()):detail=json.loads(saved[1])
   else:
    detail=fetcher.get(f'{base}/{slug}/summary?event={eid}')
    header=detail.get('header',{})
    if str(header.get('id',''))!=eid or len(header.get('competitions',[]))!=1:raise ValueError('summary_event_mismatch')
    connection.execute('INSERT OR REPLACE INTO summaries VALUES(?,?,?,?,?)',(source['id'],eid,signature,json.dumps(detail),now()));connection.commit()
   dc=detail['header']['competitions'][0];ds={t['homeAway']:t for t in dc['competitors']}
   if len(dc['competitors'])!=2 or set(ds)!={'home','away'}:raise ValueError('summary_competitors')
   if any(str(ds[s]['id'])!=str(sides[s]['id']) for s in ('home','away')):raise ValueError('summary_identity_conflict')
   if type(dc.get('neutralSite')) is not bool:raise ValueError('unknown_neutral_venue')
   venue=detail.get('gameInfo',{}).get('venue') or c.get('venue') or {}
   country=venue.get('address',{}).get('country');zone=source['venue_timezones'].get(country)
   day=local_day(c['date'],country,source['venue_timezones'])
   status=(c.get('status') or event.get('status') or {}).get('type') or {}
   detail_status=dc.get('status',{}).get('type',{})
   if status.get('name')!=detail_status.get('name'):raise ValueError('summary_status_conflict')
   if any(re.search(r'aggregate|\b[12](?:st|nd) leg\b',str(n),re.I) for n in c.get('notes',[])):raise ValueError('two_leg_context_requires_adapter')
   row.update(date=day.isoformat(),neutral=dc['neutralSite'],competition=source['competition'],competition_key=source['competition_key'],
    kind='league',home_tier=source['tier'],away_tier=source['tier'],cross_border=bindings['home']['country']!=bindings['away']['country'],
    season=int(event['season']['year']),leg=0,tie_key=None,aggregate_before_home=None,aggregate_after_home=None,round_name='',
    evidence=dict(scoreboard_signature=signature,summary_sha256=digest(encoded(detail)),physical_country=country,timezone=zone,neutral_field='header.competitions[0].neutralSite'))
   if status.get('name') in ('STATUS_CANCELED','STATUS_POSTPONED','STATUS_SUSPENDED'):row.update(lifecycle='withdrawn',home_goals=None,away_goals=None,status=None)
   elif status.get('state')=='pre':row.update(lifecycle='fixture',home_goals=None,away_goals=None,status=None)
   elif status.get('completed') is True and status.get('name')=='STATUS_FULL_TIME':
    if day>as_of:raise ValueError('future_completed_result')
    for side in ('home','away'):
     score=str(sides[side].get('score',''))
     if not re.fullmatch(r'\d+',score):raise ValueError('invalid_score')
     if str(ds[side].get('score'))!=score:raise ValueError('summary_score_conflict')
     row[side+'_goals']=int(score)
    row.update(lifecycle='result',status='F')
   elif status.get('state')=='post':raise ValueError('unsupported_score_phase:'+str(status.get('name')))
   elif status.get('name') in ('STATUS_CANCELED','STATUS_POSTPONED','STATUS_SUSPENDED'):row['lifecycle']='withdrawn'
   else:row['lifecycle']='in_progress'
  except (KeyError,TypeError,ValueError,urllib.error.URLError,TimeoutError) as error:
   row['lifecycle']='unresolved';row['reasons'].append(str(error))
  output.append(row)
 return output


def event_signature(event):
 from v10_live import digest,encoded
 c=event['competitions'][0]
 return digest(encoded(dict(id=str(event['id']),date=c.get('date',event.get('date')),season=event.get('season'),status=c.get('status',event.get('status')),venue=c.get('venue'),neutral=c.get('neutralSite'),notes=c.get('notes'),competitors=[{k:t.get(k) for k in ('id','homeAway','score','linescores')} for t in c['competitors']])))
