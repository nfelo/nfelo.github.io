"""Small persistent end-of-day states; reconstruct prefixes from the last model.

A correction invalidates states at/after its first changed row. Nothing uses a
checkpoint unless the entire input prefix and the club catalogue still match.
"""
import gzip,hashlib,json,shutil
from pathlib import Path
import v10_live as live

def route_database(path,connection=None):
 c=connection or live.duckdb.connect(str(path));c.execute('DROP TABLE IF EXISTS model_route_days');c.execute('CREATE TABLE model_route_days(day VARCHAR,matches_through_day BIGINT,prefix_sha256 VARCHAR)')
 fields=','.join(live.FIELDS);cursor=c.cursor();cursor.execute('SELECT '+fields+' FROM matches ORDER BY day,match_id')
 digest=hashlib.sha256();n=0;day=None;routes=[]
 while True:
  batch=cursor.fetchmany(50000)
  if not batch:break
  for row in batch:
   current=str(row[1])
   if day and day!=current:routes.append((day,n,digest.hexdigest()))
   digest.update(live.encoded(row));n+=1;day=current
 if day:routes.append((day,n,digest.hexdigest()))
 c.executemany('INSERT INTO model_route_days VALUES(?,?,?)',routes);c.execute('CHECKPOINT')
 if connection is None:c.close()

def identity(input_path):
 c=live.duckdb.connect(str(input_path),read_only=True);clubs=live.query(c,'SELECT * FROM clubs ORDER BY club');c.close()
 return {'engine':live.ENGINE_SHA,'config':live.CONFIG_SHA,'clubs':live.digest(live.encoded(clubs))}

def resume(root,input_path,old_model,working):
 ident=identity(input_path);cache=root/'replay-states';cache.mkdir(exist_ok=True);chosen=None
 c=live.duckdb.connect(str(input_path),read_only=True)
 for p in sorted(cache.glob('*.json.gz'),reverse=True):
  saved=json.loads(gzip.decompress(p.read_bytes()))
  if saved['identity']!=ident:continue
  day=saved['state']['checkpoint_day'];row=c.execute('SELECT matches_through_day,prefix_sha256 FROM model_route_days WHERE day=?',[day]).fetchone()
  if row and list(row)==saved['route']:chosen=saved;break
 c.close()
 if not chosen:return None,ident
 day=chosen['state']['checkpoint_day'];target=working/'resume';target.mkdir(parents=True)
 live.atomic(target/'model-state.json',chosen['state']);c=live.duckdb.connect(str(old_model),read_only=True)
 for table,file,condition in [('rated_matches','rated-matches.parquet','day<=?'),('year_openings','year-openings.parquet','year<=?')]:
  value=day if table=='rated_matches' else int(day[:4]);c.execute('COPY (SELECT * FROM '+table+' WHERE '+condition+") TO '"+str(target/file).replace("'","''")+"' (FORMAT PARQUET,COMPRESSION ZSTD)",[value])
 n=c.execute('SELECT count(*) FROM year_openings WHERE year<=?',[int(day[:4])]).fetchone()[0];c.close()
 files={p.name:{'bytes':p.stat().st_size,'sha256':live.file_sha(p)} for p in target.iterdir()}
 live.atomic(target/'checkpoint.json',{'schema_version':1,'checkpoint_day':day,'matches':chosen['route'][0],'input_prefix_sha256':chosen['route'][1],'identity':ident,'tables':{'rated_matches':chosen['route'][0],'year_openings':n},'files':files})
 return target,ident

def save_states(root,input_path,checkpoint_directory,ident):
 c=live.duckdb.connect(str(input_path),read_only=True);cache=root/'replay-states';cache.mkdir(exist_ok=True)
 for path in checkpoint_directory.glob('*/model-state.json'):
  state=live.read_json(path);day=state['checkpoint_day'];route=c.execute('SELECT matches_through_day,prefix_sha256 FROM model_route_days WHERE day=?',[day]).fetchone()
  live.atomic(cache/(day+'.json.gz'),gzip.compress(live.encoded({'identity':ident,'route':list(route),'state':state}),mtime=0))
 c.close()
 # A month of daily states catches ordinary late corrections. Older changes
 # deliberately fall back to a full replay instead of reusing a stale prefix.
 for path in sorted(cache.glob('*.json.gz'))[:-35]:path.unlink()
 shutil.rmtree(checkpoint_directory)
