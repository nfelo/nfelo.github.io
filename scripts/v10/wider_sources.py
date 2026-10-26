"""Automatic season discovery and bounded, persistent GSA round reconciliation."""
import json,re
from datetime import datetime,timezone
from urllib.parse import urljoin
from lxml import html
from free_sources import gsa,years

def season_links(text):
 tree=html.fromstring(text);out=[]
 for node in tree.xpath('//*[contains(@class,"gsa-comp-dropdown__list")]'):
  for a in node.xpath('.//a[contains(@href,"/soccer/competition/")]'):
   label=' '.join(a.text_content().split());url=a.get('href','')
   if re.fullmatch(r'20\d\d(?:[/-](?:20)?\d\d)?',label):out.append((max(years(url),default=0),url))
 return sorted(set(out),reverse=True)

def round_keys(text,season_id):
 keys=[]
 for node in html.fromstring(text).xpath('//*[@data-weeks]'):
  if node.get('data-competition_id')!=str(season_id):continue
  raw=json.loads(node.get('data-weeks') or '{}')
  if isinstance(raw,dict):keys.extend(k for k in raw if re.fullmatch(r'\d+_\d+',k))
 return sorted(set(keys),key=lambda k:tuple(map(int,k.split('_'))))

def collect_gsa(source,fetcher,as_of,connection,old=()):
 connection.execute('CREATE TABLE IF NOT EXISTS gsa_rounds(source TEXT,season TEXT,round TEXT,checked_at TEXT,PRIMARY KEY(source,season,round))')
 connection.execute('CREATE TABLE IF NOT EXISTS wider_seasons(source TEXT PRIMARY KEY,url TEXT,season TEXT)')
 saved=connection.execute('SELECT url,season FROM wider_seasons WHERE source=?',(source['id'],)).fetchone()
 url,pid=saved if saved else (source['url'],source['provider_id']);page=fetcher.text(url);links=season_links(page)
 if links and links[0][0]>=max(years(url),default=0) and links[0][0]<=as_of.year+1:
  candidate=urljoin(url,links[0][1]);newpid=candidate.rstrip('/').rsplit('/',1)[-1]
  if newpid!=pid:page=fetcher.text(candidate);url,pid=candidate,newpid
 if str(pid) not in page:raise ValueError('season_identity_missing')
 source['provider_id']=pid;connection.execute('INSERT OR REPLACE INTO wider_seasons VALUES(?,?,?)',(source['id'],url,pid))
 rows={r['id']:r for r in old};rows.update({r['id']:r for r in gsa(page,source)});keys=round_keys(page,pid)
 checked=dict(connection.execute('SELECT round,checked_at FROM gsa_rounds WHERE source=? AND season=?',(source['id'],pid)))
 selected=sorted(keys,key=lambda k:(checked.get(k,''),keys.index(k)))[:source.get('rounds_per_refresh',4)]
 for key in selected:
  try:
   text=fetcher.text('https://globalsportsarchive.com/en/widget/match_competition_round_gameweek',{'sport':'soccer','roundKey':key.split('_')[0],'activeSubRoundKey':key,'competitionId':pid,'user_timezone':source.get('timezone','UTC')})
   part=gsa(text,source)
   if not part:raise ValueError('round_returned_no_match_records')
   rows.update({r['id']:r for r in part});connection.execute('INSERT OR REPLACE INTO gsa_rounds VALUES(?,?,?,?)',(source['id'],pid,key,datetime.now(timezone.utc).isoformat()));checked[key]='retrieved'
  except Exception as e:source.setdefault('_warnings',[]).append({'round':key,'error':str(e)})
 remaining=len(set(keys)-set(checked))
 if remaining or not keys:source.setdefault('_warnings',[]).append({'rounds_remaining':remaining,'round_enumeration_available':bool(keys)})
 source['_backfill']={'season_id':pid,'rounds_listed':len(keys),'rounds_retrieved':len(set(keys)&set(checked)),'rounds_remaining':remaining};connection.commit()
 return list(rows.values())
