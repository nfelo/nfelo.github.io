#!/usr/bin/env python3
"""Portable, deterministic state for GitHub/phone installation; no model replay."""
import argparse,gzip,json,os,shutil,sqlite3,tempfile
from pathlib import Path
import v10_live as live
TABLES={'input':{'matches':['match_id'],'clubs':['club']},'model':{'rated_matches':['match_id'],'current_club_ratings':['club'],'current_country_ratings':['country'],'current_confederation_ratings':['confederation'],'year_openings':['year','club']}}

def signature(c,table):
 fields=[r[0] for r in c.execute('DESCRIBE '+table).fetchall()];expr='hash('+','.join('"'+f+'"' for f in fields)+')'
 row=c.execute('SELECT count(*),coalesce(bit_xor('+expr+'),0),coalesce(sum(cast('+expr+' as HUGEINT)),0) FROM '+table).fetchone()
 return dict(count=row[0],xor=str(row[1]),sum=str(row[2]))

def pack(state,destination):
 state=state.resolve();destination=destination.resolve();destination.parent.mkdir(parents=True,exist_ok=True)
 with live.locked(state),tempfile.TemporaryDirectory(dir=destination.parent,prefix='.v10-pack-') as temp:
  stage=Path(temp);cur=live.read_json(state/'current.json');manifest=dict(schema=1,current=cur,tables={},engine_sha256=live.ENGINE_SHA,config_sha256=live.CONFIG_SHA)
  for kind,tables in TABLES.items():
   c=live.duckdb.connect(str(state/cur[kind]),read_only=True);c.execute('SET threads=1');manifest['tables'][kind]={}
   for table,keys in tables.items():
    desc=c.execute('DESCRIBE '+table).fetchall();spec=dict(columns=[(r[0],r[1]) for r in desc],signature=signature(c,table),files=[])
    years=[r[0] for r in c.execute('SELECT distinct year(day) FROM '+table+' ORDER BY 1').fetchall()] if table in ('matches','rated_matches') else [None]
    for year in years:
     name=kind+'/'+table+('/'+str(year) if year is not None else '')+'.parquet';path=stage/name;path.parent.mkdir(parents=True,exist_ok=True)
     sql='SELECT * FROM '+table+(' WHERE year(day)='+str(int(year)) if year is not None else '')+' ORDER BY '+','.join(keys)
     c.execute('COPY ('+sql+') TO ? (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)',[str(path)])
     if path.stat().st_size>90*1024*1024:raise ValueError('State part exceeds GitHub file limit')
     spec['files'].append(name)
    manifest['tables'][kind][table]=spec
   c.close()
  for name in ['config.json','last_run.json']:
   if (state/name).exists():shutil.copy2(state/name,stage/name)
  if (state/'observations.sqlite').exists():
   src=sqlite3.connect(state/'observations.sqlite');db=stage/'observations.sqlite';dst=sqlite3.connect(db);src.backup(dst);src.close()
   # Raw HTTP objects are a local cache. Persist only the minimal source facts needed by the adapter.
   dst.execute('DELETE FROM requests')
   for source,eid,payload in dst.execute('SELECT source,event_id,payload FROM summaries').fetchall():
    raw=json.loads(payload);header=raw.get('header',{});small={'header':{'id':header.get('id'),'competitions':header.get('competitions',[])},'gameInfo':{'venue':raw.get('gameInfo',{}).get('venue')}}
    dst.execute('UPDATE summaries SET payload=? WHERE source=? AND event_id=?',(json.dumps(small,separators=(',',':')),source,eid))
   dst.commit();dst.execute('VACUUM');dst.close()
   with db.open('rb') as a,(stage/'observations.sqlite.gz').open('wb') as raw:
    with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as b:shutil.copyfileobj(a,b)
   db.unlink()
  live.atomic(stage/'MANIFEST.json',manifest)
  hashes={str(p.relative_to(stage)):live.file_sha(p) for p in stage.rglob('*') if p.is_file()};live.atomic(stage/'CHECKSUMS.json',hashes)
  destination.mkdir(parents=True,exist_ok=True)
  for p in stage.rglob('*'):
   if p.is_file():
    out=destination/p.relative_to(stage);out.parent.mkdir(parents=True,exist_ok=True)
    if not out.exists() or live.file_sha(out)!=live.file_sha(p):os.replace(p,out)
  allowed=set(hashes)|{'CHECKSUMS.json'}
  for p in destination.rglob('*'):
   if p.is_file() and str(p.relative_to(destination)) not in allowed:p.unlink()
  result=dict(files=len(allowed),bytes=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()),matches=manifest['tables']['input']['matches']['signature']['count'],model_replayed=False)
  return result

def hydrate(bundle,state,site=None):
 if state.exists():raise ValueError('Runtime destination already exists; retain it or choose a fresh path')
 bundle=bundle.resolve();hashes=live.read_json(bundle/'CHECKSUMS.json')
 for name,sha in hashes.items():
  p=(bundle/name).resolve()
  if not p.is_relative_to(bundle) or live.file_sha(p)!=sha:raise ValueError('State checksum differs: '+name)
 manifest=live.read_json(bundle/'MANIFEST.json');state.mkdir(parents=True);generation=state/'generations/seed';generation.mkdir(parents=True)
 try:
  for kind,tables in manifest['tables'].items():
   c=live.duckdb.connect(str(generation/(kind+'.duckdb')))
   for table,spec in tables.items():
    cols=','.join('"'+name+'" '+typ for name,typ in spec['columns']);c.execute('CREATE TABLE '+table+'('+cols+')')
    for name in spec['files']:c.execute('INSERT INTO '+table+' SELECT * FROM read_parquet(?)',[str(bundle/name)])
    if signature(c,table)!=spec['signature']:raise ValueError('Typed state differs: '+kind+'.'+table)
   if kind=='input':
    c.execute('CREATE UNIQUE INDEX live_match_id ON matches(match_id)');c.execute('CREATE INDEX live_match_day ON matches(day)')
   else:c.execute('CREATE VIEW current_association_ratings AS SELECT country,rating,se,international_updates FROM current_country_ratings')
   c.execute('CHECKPOINT');c.close()
  for name in ['config.json','last_run.json']:
   if (bundle/name).exists():shutil.copy2(bundle/name,state/name)
  if (bundle/'observations.sqlite.gz').exists():
   with gzip.open(bundle/'observations.sqlite.gz','rb') as a,(state/'observations.sqlite').open('wb') as b:shutil.copyfileobj(a,b)
  (state/'objects').mkdir()
  current=dict(manifest['current'],generation='seed',input='generations/seed/input.duckdb',model='generations/seed/model.duckdb',site=None)
  if site and (site/'clubs').is_dir():
   shutil.copytree(site/'clubs',generation/'site/clubs');current['site']='generations/seed/site'
   for name in ('assets','favicon-2026.svg'):
    p=site/name
    if p.is_dir():shutil.copytree(p,generation/'site'/name)
    elif p.is_file():shutil.copy2(p,generation/'site'/name)
  validation=live.validate_model(generation/'input.duckdb',generation/'model.duckdb');live.atomic(state/'RESTORE_VERIFIED.json',validation);live.atomic(state/'current.json',current)
  return dict(restored_without_model_replay=True,**validation)
 except Exception:
  live.atomic(state/'RESTORE_FAILED.json',{'error':'Incomplete restoration; do not use'});raise

def compare(a,b):
 ca=live.read_json(a/'current.json');cb=live.read_json(b/'current.json');result={}
 for kind,tables in TABLES.items():
  c=live.duckdb.connect(str(a/ca[kind]),read_only=True);c.execute("ATTACH '"+str(b/cb[kind]).replace("'","''")+"' AS restored (READ_ONLY)")
  for table in tables:
   for lhs,rhs in [(table,'restored.'+table),('restored.'+table,table)]:
    n=c.execute('SELECT count(*) FROM ((SELECT * FROM '+lhs+') EXCEPT ALL (SELECT * FROM '+rhs+'))').fetchone()[0];result[kind+':'+lhs+'->'+rhs]=n
    if n:raise ValueError('Reconstructed native values differ')
  c.close()
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
 x=s.add_parser('pack');x.add_argument('--state',type=Path,required=True);x.add_argument('--output',type=Path,required=True)
 x=s.add_parser('hydrate');x.add_argument('--bundle',type=Path,required=True);x.add_argument('--state',type=Path,required=True);x.add_argument('--site',type=Path)
 x=s.add_parser('compare');x.add_argument('--expected',type=Path,required=True);x.add_argument('--restored',type=Path,required=True)
 a=p.parse_args();r=pack(a.state,a.output) if a.command=='pack' else hydrate(a.bundle,a.state,a.site) if a.command=='hydrate' else compare(a.expected,a.restored);print(json.dumps(r,indent=2))
