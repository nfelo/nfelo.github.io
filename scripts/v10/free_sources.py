"""Public result feeds, normalized without changing provider identities.

Lists are not coverage claims. Unexplained truncation retains the prior snapshot;
unsupported phases remain observations and cannot silently become rated matches.
"""
from datetime import datetime,timezone
import re
from urllib.parse import urlencode
FOTMOB='https://www.fotmob.com/api/data'
ESPN='https://site.api.espn.com/apis/site/v2/sports/soccer'
EXCLUDED=re.compile(r'\bwomen|\bfemin|\bfemeni|\bu[ -]?(?:1[0-9]|2[0-3])\b|under[ -]?\d|youth|primavera|revelacao|reserve|premier league 2|friendly|friendlies|futsal|beach soccer',re.I)
def eligible(name):return not EXCLUDED.search(name or '')
def years(season):return [int(x) for x in re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',str(season))]
def score(value):
 m=re.fullmatch(r'\s*(\d+)\s*[-:]\s*(\d+)\s*',str(value))
 if not m:raise ValueError('invalid_score')
 return int(m[1]),int(m[2])
def unique(rows):
 out={}
 for r in rows:
  if not r.get('id'):raise ValueError('missing_event_id')
  if r['id'] in out and out[r['id']]!=r:raise ValueError('conflicting_duplicate_event:'+r['id'])
  out[r['id']]=r
 return list(out.values())
def fotmob(payload,source):
 d=(payload or {}).get('details') or {}
 if str(d.get('id'))!=str(source['provider_id']):raise ValueError('competition_identity_changed')
 if d.get('gender')!='male' or not eligible(d.get('name')):raise ValueError('outside_senior_men_scope')
 matches=(payload.get('fixtures') or payload.get('matches') or {}).get('allMatches')
 if not isinstance(matches,list):raise ValueError('missing_complete_match_list')
 out=[];season=d.get('selectedSeason') or d.get('latestSeason')
 for m in matches:
  s=m.get('status') or {};phase=(s.get('reason') or {}).get('short')
  r=dict(id=str(m.get('id') or ''),provider='fotmob',kickoff=s.get('utcTime'),season=max(years(season),default=None),season_label=season,round_name=str(m.get('round') or m.get('roundName') or ''),lifecycle='fixture',status=None,home_goals=None,away_goals=None,leg=None,neutral=None,raw_status=s)
  for side in ('home','away'):
   t=m.get(side) or {};r[side+'_id']=str(t.get('id') or '');r[side+'_name']=t.get('name')
  if s.get('cancelled'):r['lifecycle']='withdrawn'
  elif s.get('awarded') or phase in ('AW','Ab'):r.update(lifecycle='unresolved',reasons=['awarded_or_abandoned'])
  elif s.get('finished'):
   try:r['home_goals'],r['away_goals']=score(s.get('scoreStr'));r.update(lifecycle='result',status={'FT':'F','AET':'E','Pen':'P'}[phase])
   except (ValueError,KeyError):r.update(lifecycle='unresolved',reasons=['unknown_score_phase:'+str(phase)])
  elif s.get('started'):r['lifecycle']='in_progress'
  out.append(r)
 # The bracket supplies explicit best-of and first/second-leg order. It is
 # safer than guessing from a pair of reverse fixtures (which can be a replay).
 lookup={r['id']:r for r in out}
 def bracket(node):
  if isinstance(node,list):
   for x in node:bracket(x)
  elif isinstance(node,dict):
   if node.get('bestOf') in (1,2) and isinstance(node.get('matches'),list):
    games=sorted(node['matches'],key=lambda x:(x.get('status') or {}).get('utcTime',''))
    for i,g in enumerate(games):
     r=lookup.get(str(g.get('matchId')))
     if r is None:continue
     r['leg']=i+1 if node['bestOf']==2 else 0;r['tie_round']=str(node.get('stage',''))
     before=0
     if i:
      first=games[0]
      try:
       firstscore=score(first['status']['scoreStr']);before=firstscore[0]-firstscore[1]
       if str(first['home']['id'])!=r['home_id']:before=-before
      except (ValueError,KeyError,TypeError):before=None
     r['aggregate_before_home']=before if r['leg'] else None
     r['aggregate_after_home']=before+r['home_goals']-r['away_goals'] if r['leg'] and before is not None and r['home_goals'] is not None else None
   for x in node.values():
    if isinstance(x,(list,dict)):bracket(x)
 bracket(payload.get('playoff') or {})
 return unique(out)
def espn(payload,source):
 if not isinstance(payload.get('events'),list):raise ValueError('missing_events')
 out=[]
 for e in payload['events']:
  r=dict(id=str(e.get('id') or ''),provider='espn',kickoff=e.get('date'),season=(e.get('season') or {}).get('year'),lifecycle='unresolved',reasons=[])
  try:
   if len(e.get('competitions',[]))!=1:raise ValueError('competition_count')
   c=e['competitions'][0];teams={x['homeAway']:x for x in c['competitors']}
   if len(c['competitors'])!=2 or set(teams)!={'home','away'}:raise ValueError('competitors')
   s=(c.get('status') or e.get('status') or {}).get('type') or {}
   r.update(kickoff=c.get('date',e.get('date')),neutral=c.get('neutralSite'),leg=c.get('leg'),round_name=str((c.get('type') or {}).get('text') or ''),venue_country=((c.get('venue') or {}).get('address') or {}).get('country'),notes=c.get('notes',[]),raw_status=s)
   for side,t in teams.items():
    r[side+'_id']=str(t['team']['id']);r[side+'_name']=t['team'].get('displayName');r[side+'_goals']=int(t['score']) if str(t.get('score','')).isdigit() else None
    r[side+'_shootout']=t.get('shootoutScore');r[side+'_aggregate']=t.get('aggregateScore')
   groups={str((t.get('team',{}).get('groups') or {}).get('name') or '') for t in teams.values()}
   if len(groups)==1 and next(iter(groups)):r['round_name']=next(iter(groups))
   notes=' '.join(str(x) for x in r['notes']);leg=re.search(r'([12])(?:st|nd) leg',notes,re.I)
   if leg:r['leg']=int(leg[1])
   if r.get('leg')==1:r.update(aggregate_before_home=0,aggregate_after_home=(r['home_goals']-r['away_goals']) if r['home_goals'] is not None and r['away_goals'] is not None else None)
   if r.get('leg')==2 and r.get('home_aggregate') is not None and r.get('away_aggregate') is not None and r['home_goals'] is not None:
    after=int(float(r['home_aggregate']))-int(float(r['away_aggregate']));r.update(aggregate_after_home=after,aggregate_before_home=after-r['home_goals']+r['away_goals'])
   name=s.get('name');r['status']={'STATUS_FULL_TIME':'F','STATUS_FINAL_AET':'E','STATUS_FINAL_PEN':'P'}.get(name)
   if name in ('STATUS_CANCELED','STATUS_POSTPONED','STATUS_SUSPENDED'):r['lifecycle']='withdrawn'
   elif s.get('completed') and r['status']:r['lifecycle']='result'
   elif s.get('state')=='pre':r['lifecycle']='fixture'
   elif s.get('state')=='in':r['lifecycle']='in_progress'
   else:r['reasons']=['unsupported_score_phase:'+str(name)]
  except (KeyError,TypeError,ValueError) as ex:r['reasons']=[str(ex)]
  out.append(r)
 return unique(out)
def soccerway(text,source):
 rows=[];found=False
 for m in re.finditer(r'''cjs\.initialFeeds\[['"](results|fixtures)['"]\]\s*=\s*\{\s*data:\s*`([^`]*)`([^}]+)''',text,re.S):
  feed,data,tail=m.groups();found=True;part=[]
  for block in data.split('~'):
   f=dict(x.split('÷',1) for x in block.split('¬') if '÷' in x)
   if 'AA' not in f:continue
   stamp=datetime.fromtimestamp(int(f['AD']),timezone.utc)
   r=dict(id=f['AA'],provider='soccerway',kickoff=stamp.isoformat(),season=stamp.year,home_id=f.get('PX'),away_id=f.get('PY'),home_name=f.get('AE'),away_name=f.get('AF'),round_name=f.get('ER',''),raw_fields=f,leg=None,neutral=None,status=None,home_goals=None,away_goals=None,lifecycle='fixture')
   if feed=='results':
    if f.get('AC')=='3' and str(f.get('AG','')).isdigit() and str(f.get('AH','')).isdigit():r.update(lifecycle='result',status='F',home_goals=int(f['AG']),away_goals=int(f['AH']))
    else:r.update(lifecycle='unresolved',reasons=['score_phase_needs_detail:'+str(f.get('AC'))])
   part.append(r)
  n=re.search(r'allEventsCount:\s*(\d+)',tail)
  if n and int(n[1])>len(part):raise ValueError('incomplete_pagination:'+str(len(part))+'/'+n[1])
  rows.extend(part)
 if not found:raise ValueError('missing_embedded_feeds')
 return unique(rows)
def load_route(source,fetcher,as_of,bootstrap=False):
 pid=source['provider_id'];provider=source['provider']
 if provider=='fotmob':
  url=f'{FOTMOB}/leagues?id={pid}';p=fetcher.get(url);rows=fotmob(p,source);selected=p['details'].get('selectedSeason')
  for season in p.get('allAvailableSeasons') or []:
   yy=years(season)
   if season!=selected and yy and min(yy)<=as_of.year and max(yy)>=as_of.year-(1 if bootstrap else 0):
    try:
     archive=fetcher.get(url+'&'+urlencode({'season':season}))
     if not isinstance(archive,dict) or (archive.get('details') or {}).get('selectedSeason')!=season:raise ValueError('requested_season_not_returned')
     rows.extend(fotmob(archive,source))
    except Exception as e:source.setdefault('_warnings',[]).append({'season':season,'error':str(e)})
  return unique(rows)
 if provider=='espn':
  rows=[]
  for year in range(as_of.year-(1 if bootstrap else 0),as_of.year+1):
   try:p=fetcher.get(f'{ESPN}/{pid}/scoreboard?dates={year}&limit=1000')
   except Exception as e:
    if year==as_of.year:raise
    source.setdefault('_warnings',[]).append({'season':str(year),'error':str(e)});continue
   if len(p.get('events',[]))>=1000:
    parent={str(x['id']) for x in p['events']};parts=[]
    for month in range(1,13):
     q=fetcher.get(f'{ESPN}/{pid}/scoreboard?dates={year}{month:02d}&limit=1000')
     if len(q.get('events',[]))>=1000:raise ValueError('incomplete_month_pagination')
     parts.extend(espn(q,source))
    if not parent<={x['id'] for x in parts}:raise ValueError('pagination_lost_events')
    rows.extend(parts)
   else:rows.extend(espn(p,source))
  return unique(rows)
 if provider=='soccerway':return soccerway(fetcher.text(source['url']),source)
 if provider=='gsa':
  # The widget can return a whole round; overlapping days are deduplicated.
  from datetime import timedelta
  rows=[]
  for offset in range(source.get('lookback_days',7),-1,-1):
   text=fetcher.text('https://globalsportsarchive.com/en/widget/competition_day_rounds',{'sport':'soccer','date':str(as_of-timedelta(days=offset)),'season_id':pid,'variant':'narrow'})
   rows.extend(gsa(text,source))
  return unique(rows)
 if provider=='ofc':
  text=fetcher.text(source['url'].format(year=as_of.year))
  from lxml import html
  description=' '.join(html.fromstring(text).xpath('//meta[@name="description"]/@content'))
  host=re.search(r'held in ([A-Za-z ]+?) (?:from|on)',description)
  if host:source['host']=host[1]
  return ofc(text,source)

 raise ValueError('unknown_provider:'+provider)

def gsa(text,source):
 """League widget: explicit played-score elements and provider local dates."""
 from lxml import html
 tree=html.fromstring(text);out=[]
 for node in tree.xpath('//*[@data-match_id]'):
  logos=node.xpath('.//img[contains(@src,"/clubs/")]');teams=[]
  for logo in logos:
   m=re.search(r'/clubs/[^/]+/(\d+)\.',logo.get('src',''))
   if m:teams.append((m[1],(logo.get('alt') or '').removeprefix('logo of ')))
  raw=' '.join(node.text_content().split());day=re.search(r'(\d\d)\.(\d\d)\.(20\d\d)',raw)
  if len(teams)!=2 or not day:continue
  goals=[''.join(x.itertext()).strip() for x in node.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," gsa-match-played ")]')]
  r=dict(id=str(node.get('data-match_id')),provider='gsa',date=f'{day[3]}-{day[2]}-{day[1]}',date_basis='provider_local_date',season=int(day[3]),home_id=teams[0][0],away_id=teams[1][0],home_name=teams[0][1],away_name=teams[1][1],round_name='',leg=0 if source['kind']=='league' else None,neutral=None,lifecycle='unresolved',reasons=['unconfirmed_score_phase'],status=None,home_goals=None,away_goals=None)
  if len(goals)==1:
   try:goals=list(map(str,score(goals[0])))
   except ValueError:pass
  if source['kind']=='league' and len(goals)==2 and all(x.isdigit() for x in goals):r.update(lifecycle='result',status='F',home_goals=int(goals[0]),away_goals=int(goals[1]),reasons=[])
  out.append(r)
 return unique(out)

def ofc(text,source):
 """Official COMET fixture table; match IDs and local match dates retained."""
 from lxml import html
 out=[];tree=html.fromstring(text)
 for tr in tree.xpath('//tr[td[contains(@class,"general-info")]]'):
  def value(cls):return ' '.join(tr.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," '+cls+' ")]//text()')).strip()
  home=value('team1');away=value('team2');stamp=value('date');href=tr.xpath('.//td[contains(@class,"link-more")]//a/@href');m=re.fullmatch(r'(\d\d)\.(\d\d)\.(20\d\d)\.',stamp)
  if not home or not away or not href or not m:continue
  event=re.search(r'-(\d+)/?$',href[0])
  if not event:continue
  r=dict(id=event[1],provider='ofc',date=f'{m[3]}-{m[2]}-{m[1]}',date_basis='provider_local_date',season=int(m[3]),home_id=home,away_id=away,home_name=home,away_name=away,round_name='',leg=0,neutral=True,venue_country=source.get('qualifying_host') if 'qualifying' in href[0] else source.get('host'),venue=value('stadium'),lifecycle='fixture',home_goals=None,away_goals=None,status=None)
  try:r['home_goals'],r['away_goals']=score(value('result'));r.update(lifecycle='result',status='F')
  except ValueError:
   if re.search(r'\d',value('result')):r.update(lifecycle='unresolved',reasons=['unconfirmed_score_phase'])
  out.append(r)
 if not out:raise ValueError('missing_comet_schedule')
 return unique(out)
