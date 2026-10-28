#!/usr/bin/env python3
"""Persistent source refresh -> canonical ledger -> frozen model -> atomic site.

Sources and exceptions survive failed builds. current.json advances only after
the complete next generation succeeds. This command never enables scheduling
or pushes/deploys anything. The inherited historical coverage remains explicit.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import gzip, hashlib, html, json, os, re, shutil, sqlite3, sys, time
from pathlib import Path
import urllib.request, urllib.error
import uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'engine'))
import duckdb
from club_model import load_club_config, run_club_model
FIELDS=('match_id','day','season','home','away','home_goals','away_goals','competition',
 'competition_key','kind','home_tier','away_tier','neutral','cross_border','status','leg',
 'tie_key','round_name','source','source_ref','aggregate_before_home','aggregate_after_home')
ENGINE_SHA='ba74406f8d3002c727ff6780bec74e38cd30063aad17bb12db3ab59ee01a9ff2'
CONFIG_SHA='0accb8c8666c8041d49b0ebadf7ab89519eb4bbeb525742e4134c94479cb9a72'

def encoded(v):
 return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False,
                    default=lambda x:x.isoformat())+'\n').encode()
def digest(b):return hashlib.sha256(b).hexdigest()
def file_sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def read_json(p):return json.loads(Path(p).read_text())
def atomic(p,value):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_name('.'+p.name+'.'+uuid.uuid4().hex+'.tmp')
 with tmp.open('wb') as f:f.write(value if isinstance(value,bytes) else encoded(value));f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
def query(c,sql,args=()):
 r=c.execute(sql,args);names=[v[0] for v in r.description]
 return [dict(zip(names,row)) for row in r.fetchall()]
@contextmanager
def locked(root):
 import fcntl
 root.mkdir(parents=True,exist_ok=True)
 with (root/'update.lock').open('a+b') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise RuntimeError('Another update is already running') from None
  yield

def state_db(root):
 c=sqlite3.connect(root/'observations.sqlite',timeout=30)
 c.execute('PRAGMA journal_mode=DELETE');c.execute('PRAGMA synchronous=FULL')
 c.executescript('''
 CREATE TABLE IF NOT EXISTS requests(url TEXT PRIMARY KEY,sha TEXT,etag TEXT,modified TEXT,fetched_at TEXT);
 CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,last_success TEXT,last_attempt TEXT,error TEXT,cursor TEXT,row_count INTEGER);
 CREATE TABLE IF NOT EXISTS observations(source TEXT,event_id TEXT,payload TEXT,sha TEXT,observed_at TEXT,PRIMARY KEY(source,event_id));
 CREATE TABLE IF NOT EXISTS summaries(source TEXT,event_id TEXT,signature TEXT,payload TEXT,checked_at TEXT,PRIMARY KEY(source,event_id));
 ''');return c

class Fetcher:
 def __init__(self,root,connection,timeout=20):
  self.root,self.connection,self.timeout=root,connection,timeout
  self.requests=self.unchanged=0
  self.prefetched={}
 def text(self,url,form=None):
  """Bounded public HTML transport; POST bodies are part of the cache key."""
  import urllib.parse
  body=None if form is None else urllib.parse.urlencode(form).encode()
  key=url if body is None else url+'#post='+digest(body)
  headers={'User-Agent':'NFElo-club-updater/2.0','Accept-Encoding':'identity'}
  old=self.connection.execute('SELECT sha,etag,modified FROM requests WHERE url=?',(key,)).fetchone()
  if old and body is None:
   if old[1]:headers['If-None-Match']=old[1]
   if old[2]:headers['If-Modified-Since']=old[2]
  self.requests+=1
  try:
   with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers),timeout=self.timeout) as response:
    raw=response.read(32*1024*1024+1);etag=response.headers.get('ETag');modified=response.headers.get('Last-Modified')
   if len(raw)>32*1024*1024:raise ValueError('Source response exceeds 32 MiB')
  except urllib.error.HTTPError as e:
   if e.code!=304 or not old:raise
   raw=gzip.decompress((self.root/'objects'/(old[0]+'.json.gz')).read_bytes())
   if digest(raw)!=old[0]:raise ValueError('Cached response hash differs')
   self.unchanged+=1;return raw.decode('utf-8')
  if raw[:2]==b'\x1f\x8b':raw=gzip.decompress(raw)
  sha=digest(raw);path=self.root/'objects'/(sha+'.json.gz')
  if not path.exists():atomic(path,gzip.compress(raw,mtime=0))
  self.connection.execute('INSERT OR REPLACE INTO requests VALUES(?,?,?,?,?)',(key,sha,etag,modified,now()));self.connection.commit()
  if old and old[0]==sha:self.unchanged+=1
  return raw.decode('utf-8')
 def prefetch(self,urls,workers=4):
  from concurrent.futures import ThreadPoolExecutor,as_completed
  def worker(url):
   for attempt in range(2):
    try:
     request=urllib.request.Request(url,headers={'User-Agent':'NFElo-V10-updater/1.0','Accept':'application/json','Accept-Encoding':'identity'})
     with urllib.request.urlopen(request,timeout=self.timeout) as response:
      raw=response.read(32*1024*1024+1);etag=response.headers.get('ETag');modified=response.headers.get('Last-Modified')
     if len(raw)>32*1024*1024:raise ValueError('Source response exceeds 32 MiB')
     if raw[:2]==b'\x1f\x8b':raw=gzip.decompress(raw)
     value=json.loads(raw);return url,value,raw,etag,modified,attempt+1
    except (urllib.error.URLError,TimeoutError) as e:
     if attempt==0:continue
     return url,e,None,None,None,attempt+1
    except Exception as e:return url,e,None,None,None,attempt+1
  with ThreadPoolExecutor(max_workers=workers) as pool:
   for future in as_completed([pool.submit(worker,u) for u in sorted(set(urls))]):
    url,value,raw,etag,modified,requests=future.result();self.requests+=requests;self.prefetched[url]=value
    if raw is None:continue
    sha=digest(raw);old=self.connection.execute('SELECT sha FROM requests WHERE url=?',(url,)).fetchone()
    if old and old[0]==sha:self.unchanged+=1
    path=self.root/'objects'/(sha+'.json.gz')
    if not path.exists():atomic(path,gzip.compress(raw,mtime=0))
    self.connection.execute('INSERT OR REPLACE INTO requests VALUES(?,?,?,?,?)',(url,sha,etag,modified,now()));self.connection.commit()
 def get(self,url):
  if url in self.prefetched:
   value=self.prefetched.pop(url)
   if isinstance(value,Exception):raise value
   return value
  if not re.match(r'^https?://',url):raise ValueError('Source must use HTTP(S)')
  old=self.connection.execute('SELECT sha,etag,modified FROM requests WHERE url=?',(url,)).fetchone()
  headers={'User-Agent':'NFElo-V10-updater/1.0','Accept':'application/json','Accept-Encoding':'identity'}
  if old:
   if old[1]:headers['If-None-Match']=old[1]
   if old[2]:headers['If-Modified-Since']=old[2]
  for attempt in range(2):
   self.requests+=1
   try:
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=self.timeout) as response:
     raw=response.read(32*1024*1024+1);etag=response.headers.get('ETag');modified=response.headers.get('Last-Modified')
    if len(raw)>32*1024*1024:raise ValueError('Source response exceeds 32 MiB')
    break
   except urllib.error.HTTPError as e:
    if e.code==304 and old:
     raw=gzip.decompress((self.root/'objects'/(old[0]+'.json.gz')).read_bytes())
     if digest(raw)!=old[0]:raise ValueError('Cached response hash differs')
     self.unchanged+=1;return json.loads(raw)
    if attempt==0 and e.code in (429,500,502,503,504):time.sleep(0.5);continue
    raise
   except (urllib.error.URLError,TimeoutError):
    if attempt==0:continue
    raise
  if raw[:2]==b'\x1f\x8b':raw=gzip.decompress(raw)
  value=json.loads(raw);sha=digest(raw);p=self.root/'objects'/(sha+'.json.gz')
  if not p.exists():atomic(p,gzip.compress(raw,mtime=0))
  if old and old[0]==sha:self.unchanged+=1
  self.connection.execute('INSERT OR REPLACE INTO requests VALUES(?,?,?,?,?)',(url,sha,etag,modified,now()))
  self.connection.commit();return value

def _collect_serial(root,config,as_of):
 c=sqlite3.connect(root/'observations.sqlite',timeout=30);fetcher=Fetcher(root,c,config.get('http_timeout',20));health=[]
 try:
  for source in config['sources']:
   sid=source['id'];prior=c.execute('SELECT last_success,cursor,row_count FROM sources WHERE id=?',(sid,)).fetchone();started=now()
   try:
    if source['adapter']=='espn_league':
     from espn_adapter import collect_espn
     source=dict(source,ledger=str(root/read_json(root/'current.json')['input']))
     rows=collect_espn(source,fetcher,c,as_of)
    elif source['adapter']=='canonical_json':
     payload=fetcher.get(source['url'])
     if not isinstance(payload,dict) or payload.get('schema')!=1 or not isinstance(payload.get('events'),list):raise ValueError('Canonical feed schema changed')
     rows=payload['events']
    else:raise ValueError('Unknown source adapter')
    ids=[r.get('id') for r in rows]
    if any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):raise ValueError('Missing or duplicate source event ID')
    if prior and prior[2] and prior[1] and prior[1][:4]==str(as_of.year) and len(rows)<prior[2]*0.5:raise ValueError('Unexpected source contraction; previous observations retained')
    with c:
     for row in rows:
      p=encoded(row);c.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?)',(sid,row['id'],p.decode(),digest(p),now()))
     c.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)',(sid,now(),started,None,as_of.isoformat(),len(rows)))
    health.append(dict(source=sid,status='healthy',rows=len(rows),last_success=now(),error=None))
   except Exception as e:
    c.rollback()
    with c:c.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)',(sid,prior[0] if prior else None,started,str(e),prior[1] if prior else None,prior[2] if prior else 0))
    health.append(dict(source=sid,status='stale' if prior else 'unavailable',last_success=prior[0] if prior else None,error=str(e)))
  enabled={s['id'] for s in config['sources']}
  observations=[(s,json.loads(p)) for s,p in c.execute('SELECT source,payload FROM observations ORDER BY source,event_id') if s in enabled]
  return observations,health,dict(http_requests=fetcher.requests,unchanged_responses=fetcher.unchanged)
 finally:c.close()

def collect(root,config,as_of):
 if config.get('free_sources'):
  from free_update import collect as collect_free
  return collect_free(root,config['free_sources'],as_of)
 c=state_db(root);c.close()
 return _collect_serial(root,config,as_of)

def model_record(source,event,clubs,as_of):
 if event.get('lifecycle')!='result':raise ValueError('not_a_final_result')
 day=date.fromisoformat(event['date'])
 if day>as_of:raise ValueError('future_completed_result')
 for side in ('home','away'):
  if type(event.get(side)) is not int or event[side] not in clubs:raise ValueError('unknown_'+side+'_identity')
  if type(event.get(side+'_goals')) is not int or not 0<=event[side+'_goals']<=100:raise ValueError('invalid_'+side+'_score')
  if type(event.get(side+'_tier')) is not int or not 1<=event[side+'_tier']<=20:raise ValueError('invalid_'+side+'_tier')
 if event['home']==event['away']:raise ValueError('self_match')
 if type(event.get('neutral')) is not bool:raise ValueError('unknown_neutral_venue')
 if type(event.get('cross_border')) is not bool:raise ValueError('unknown_cross_border')
 if event['cross_border']!=(clubs[event['home']]['country']!=clubs[event['away']]['country']):raise ValueError('cross_border_identity_mismatch')
 if event.get('status') not in ('F','E','P','P?'):raise ValueError('unknown_score_phase')
 if event['status'] in ('P','P?') and event['home_goals']!=event['away_goals'] and not (event.get('leg')==2 and event.get('aggregate_after_home')==0):raise ValueError('shootout_goals_cannot_be_rating_goals')
 if event.get('kind') not in load_club_config(HERE/'engine/club_model.json')['competition_weights']:raise ValueError('unknown_competition_kind')
 if not event.get('competition') or not event.get('competition_key'):raise ValueError('missing_competition')
 if event.get('leg') not in (0,1,2):raise ValueError('unknown_leg')
 if event['leg'] and (not event.get('tie_key') or event.get('aggregate_before_home') is None or event.get('aggregate_after_home') is None):raise ValueError('missing_two_leg_context')
 if event['leg'] and event['aggregate_after_home']!=event['aggregate_before_home']+event['home_goals']-event['away_goals']:raise ValueError('aggregate_score_mismatch')
 if type(event.get('season')) is not int:raise ValueError('missing_season')
 row={k:event.get(k) for k in FIELDS};row.update(match_id='live_'+digest((source+':'+event['id']).encode())[:27],day=day,source='v10-live',source_ref=source+':'+event['id'])
 return row

def reconcile(input_path,observations,as_of,pending_clubs=()):
 from reconcile_sources import reconcile as reconcile_all
 return reconcile_all(input_path,observations,as_of,pending_clubs)

def validate_model(input_path,model_path):
 c=duckdb.connect(str(model_path),read_only=True)
 try:
  c.execute("ATTACH '"+str(input_path).replace("'","''")+"' AS source_input (READ_ONLY)");fields=','.join(FIELDS)
  for a,b in [('rated_matches','source_input.matches'),('source_input.matches','rated_matches')]:
   if c.execute(f'SELECT count(*) FROM ((SELECT {fields} FROM {a}) EXCEPT ALL (SELECT {fields} FROM {b}))').fetchone()[0]:raise ValueError('Model output differs from ledger')
  count=c.execute('SELECT count(*) FROM rated_matches').fetchone()[0]
  if c.execute('SELECT count(*)-count(distinct match_id) FROM rated_matches').fetchone()[0]:raise ValueError('Duplicate rated match')
  bad=c.execute('''SELECT count(*) FROM rated_matches WHERE NOT isfinite(home_probability) OR NOT isfinite(draw_probability) OR NOT isfinite(away_probability)
   OR home_probability<=0 OR draw_probability<=0 OR away_probability<=0 OR abs(home_probability+draw_probability+away_probability-1)>1e-12
   OR NOT isfinite(post_home_rating) OR NOT isfinite(post_away_rating) OR home_probability IS NULL OR draw_probability IS NULL OR away_probability IS NULL''').fetchone()[0]
  if bad:raise ValueError('Invalid model numbers')
  return dict(matches=count,input_output_exact=True,invalid_probabilities=0)
 finally:c.close()

def build_site(input_path,model_path,destination,fixtures,exceptions,health,limitations,as_of,full=False,previous=None):
 if full:
  from full_site import build
  return build(input_path,model_path,destination,fixtures,exceptions,health,limitations,as_of,previous)
 destination.mkdir(parents=True,exist_ok=True);c=duckdb.connect(str(input_path),read_only=True)
 c.execute("ATTACH '"+str(model_path).replace("'","''")+"' AS model (READ_ONLY)")
 rankings=query(c,'''SELECT c.club,c.code,c.name,c.country_name,c.continent,r.rating,r.mean,r.se,r.matches,r.last_day
  FROM model.current_club_ratings r JOIN clubs c USING(club) ORDER BY r.rating DESC,c.code''')
 counts=query(c,'SELECT count(*) matches,cast(min(day) as varchar) first_date,cast(max(day) as varchar) last_date FROM matches')[0]
 recent=query(c,'''SELECT cast(m.day as varchar) date,h.name home,a.name away,m.home_goals,m.away_goals,m.competition
  FROM matches m JOIN clubs h ON h.club=m.home JOIN clubs a ON a.club=m.away ORDER BY m.day DESC,m.match_id DESC LIMIT 30''');c.close()
 meta=dict(as_of=as_of.isoformat(),results_through=counts['last_date'],first_result=counts['first_date'],matches=counts['matches'],clubs=len(rankings),
  fixtures=len(fixtures),exceptions=len(exceptions),coverage_complete=False,limitations=limitations,sources=health,generated_at=now())
 for name,value in [('rankings',rankings),('recent',recent),('fixtures',fixtures),('exceptions',exceptions),('status',meta)]:atomic(destination/(name+'.json'),value)
 rows=''.join('<tr><td>'+str(i)+'</td><td>'+html.escape(r['name'])+'</td><td>'+html.escape(r['country_name'])+'</td><td>'+format(r['rating'],'.1f')+'</td></tr>' for i,r in enumerate(rankings,1))
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NFElo Clubs — update preview</title><style>body{font:16px system-ui;background:#faf6f8;color:#42333e;margin:0}main{max-width:960px;margin:auto;padding:24px}h1{font-family:Georgia,serif}input{padding:12px;width:min(85%,420px);border:1px solid #c8acbf;border-radius:8px}table{border-collapse:collapse;width:100%;background:white}th,td{padding:9px;text-align:left;border-bottom:1px solid #eedee6}td:last-child{text-align:right;font-variant-numeric:tabular-nums}.note{padding:16px;background:#f0e4ed;border-radius:12px;margin:20px 0}a{color:#805775}</style><main><h1>NFElo · Clubs</h1>'''
 page+='<p>Results through <b>'+html.escape(counts['last_date'])+'</b> · '+format(counts['matches'],',')+' matches</p><div class="note"><b>Operational preview — historical coverage remains incomplete.</b><ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in limitations)+'</ul>'
 page+=str(len(fixtures))+' fixtures · '+str(len(exceptions))+' held records · <a href="status.json">Update status</a> · <a href="exceptions.json">Held records</a></div><input id="search" aria-label="Search clubs" placeholder="Search club or country"><table><thead><tr><th>Rank</th><th>Club</th><th>Country</th><th>Rating</th></tr></thead><tbody>'+rows+'</tbody></table></main><script>const rows=[...document.querySelectorAll("tbody tr")];document.querySelector("#search").addEventListener("input",e=>{let q=e.target.value.toLowerCase();rows.forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))});</script></html>'
 atomic(destination/'index.html',page.encode());return meta

def initialize(root,input_path,model_path,config):
 root=Path(root).resolve()
 with locked(root):
  if (root/'current.json').exists():raise ValueError('Already initialized; use update')
  validate_model(input_path,model_path);gen=root/'generations'/'seed';gen.mkdir(parents=True)
  shutil.copy2(input_path,gen/'input.duckdb');shutil.copy2(model_path,gen/'model.duckdb')
  c=duckdb.connect(str(gen/'input.duckdb'))
  count=c.execute('SELECT count(*) FROM matches').fetchone()[0]
  c.execute('CREATE INDEX IF NOT EXISTS live_match_id ON matches(match_id)')
  c.execute('CREATE INDEX IF NOT EXISTS live_match_day ON matches(day)');c.close()
  meta=dict(schema=1,generation='seed',input='generations/seed/input.duckdb',model='generations/seed/model.duckdb',site=None,created_at=now(),model_runs=0,seed_matches=count,model_identity=ENGINE_SHA+CONFIG_SHA)
  atomic(root/'config.json',config);atomic(root/'current.json',meta);return meta

def site_code_sha(full_site):
 files=['v10_live.py']
 if full_site:files+=['full_site.py','club_site_export.py','publication_checks.py']
 if full_site:files += [str(p.relative_to(HERE)) for p in sorted((HERE/'assets').rglob('*')) if p.is_file()]
 return digest(encoded({name:file_sha(HERE/name) for name in files}))

def update(root,as_of=None,*,fail_before_publish=False):
 root=Path(root).resolve();as_of=as_of or datetime.now(timezone.utc).date()
 if file_sha(HERE/'engine/club_model.py')!=ENGINE_SHA or file_sha(HERE/'engine/club_model.json')!=CONFIG_SHA:raise ValueError('Frozen engine or coefficients changed')
 with locked(root):
  current=read_json(root/'current.json');config=read_json(root/'config.json');started=time.monotonic()
  observations,health,transport=collect(root,config,as_of);old_input=root/current['input'];old_model=root/current['model']
  pending=read_json(root/'pending_clubs.json') if config.get('free_sources') and (root/'pending_clubs.json').exists() else []
  changes,fixtures,exceptions,unchanged=reconcile(old_input,observations,as_of,pending)
  if config.get('full_site'):
   from ledger_repairs import held_records
   repair_connection=duckdb.connect(str(old_input),read_only=True)
   try:exceptions.extend(held_records(repair_connection))
   finally:repair_connection.close()
  model_changed=current.get('model_identity')!=ENGINE_SHA+CONFIG_SHA
  export_sha=site_code_sha(config.get('full_site',False))
  view_sha=digest(encoded(dict(site_version=3,site_code_sha=export_sha,full_site=config.get('full_site',False),fixtures=fixtures,exceptions=exceptions,health=[{k:v for k,v in h.items() if k!='last_success'} for h in health],limitations=config['limitations'],as_of=as_of.isoformat())))
  if not changes and not model_changed and current.get('view_sha')==view_sha and current.get('site'):
   report=dict(result='no_change',generation=current['generation'],model_ran=False,changed_matches=0,fixtures=len(fixtures),exceptions=len(exceptions),sources=health,elapsed_seconds=round(time.monotonic()-started,3),**transport)
   atomic(root/'last_run.json',report);return report
  identifier=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8];gen=root/'generations'/identifier;gen.mkdir(parents=True)
  input_path,model_path=old_input,old_model
  try:
   if changes or model_changed:
    input_path=gen/'input.duckdb';model_path=gen/'model.duckdb'
    from prepare_generation import prepare
    prepare(old_input,input_path,changes,pending,historical=config.get('full_site',False))
    os.environ['PYTHONPATH']=os.pathsep.join([str(HERE/'engine'),*sys.path])
    from replay_cache import route_database,resume,save_states
    checkpoint,identity=resume(root,input_path,old_model,gen)
    result=run_club_model(input_path,load_club_config(HERE/'engine/club_model.json'),output_database=model_path,resume_checkpoint=checkpoint,checkpoint_directory=gen/'checkpoints',checkpoint_identity=identity)
    atomic(gen/'model_run.json',result);atomic(gen/'validation.json',validate_model(input_path,model_path));atomic(gen/'changes.json',changes)
   previous=root/current['site'] if current.get('site') and not changes and not model_changed and current.get('site_code_sha')==export_sha else None
   meta=build_site(input_path,model_path,gen/'site',fixtures,exceptions,health,config['limitations'],as_of,config.get('full_site',False),previous)
   next_current=dict(current,generation=identifier,input=str(input_path.relative_to(root)),model=str(model_path.relative_to(root)),site=str((gen/'site').relative_to(root)),view_sha=view_sha,site_code_sha=export_sha,created_at=now(),model_identity=ENGINE_SHA+CONFIG_SHA,model_runs=current.get('model_runs',0)+bool(changes or model_changed))
   atomic(gen/'receipt.json',dict(schema=1,prior_generation=current['generation'],input_sha256=file_sha(input_path),model_sha256=file_sha(model_path),engine_sha256=ENGINE_SHA,config_sha256=CONFIG_SHA,changes=len(changes),site=meta))
   if fail_before_publish:raise RuntimeError('Injected interruption before publication')
   atomic(root/'current.json',next_current)
   if changes or model_changed:save_states(root,input_path,gen/'checkpoints',identity)
   report=dict(result='updated' if changes or model_changed else 'site_updated',generation=identifier,model_ran=bool(changes or model_changed),model_changed=model_changed,changed_matches=len(changes),exceptions=len(exceptions),fixtures=len(fixtures),unchanged_events=unchanged,results_through=meta['results_through'],matches=meta['matches'],sources=health,elapsed_seconds=round(time.monotonic()-started,3),**transport)
   atomic(root/'last_run.json',report);return report
  except Exception as e:
   atomic(gen/'FAILED.json',dict(error=str(e),prior_generation_retained=current['generation'],time=now()));raise

def main():
 p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
 a=s.add_parser('init');a.add_argument('--state',type=Path,required=True);a.add_argument('--input',type=Path,required=True);a.add_argument('--model',type=Path,required=True);a.add_argument('--config',type=Path,required=True)
 a=s.add_parser('update');a.add_argument('--state',type=Path,required=True);a.add_argument('--as-of',type=date.fromisoformat)
 a=s.add_parser('status');a.add_argument('--state',type=Path,required=True)
 a=p.parse_args()
 if a.command=='init':result=initialize(a.state,a.input.resolve(),a.model.resolve(),read_json(a.config))
 elif a.command=='update':result=update(a.state,a.as_of)
 else:result=dict(current=read_json(a.state/'current.json'),last_run=read_json(a.state/'last_run.json') if (a.state/'last_run.json').exists() else None)
 print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=='__main__':main()
