"""Isolated ledger writer, cold-verified before any model reads the generation."""
import json,os,shutil,subprocess,sys
from pathlib import Path
import v10_live as live
from state_pack import signature
from replay_cache import route_database

def prepare(old_input,destination,changes,pending,historical=False):
 folder=destination.parent;live.atomic(folder/'changes.json',changes);live.atomic(folder/'new-clubs.json',pending)
 live.atomic(folder/'history-enabled.json',bool(historical))
 writer_path=folder/'ledger-writer.duckdb'
 r=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(old_input),str(writer_path)],capture_output=True,text=True)
 if r.returncode:raise RuntimeError('Ledger writer failed: '+r.stderr[-3000:])
 expected=live.read_json(folder/'input-signatures.json');base=folder/'input-verified.duckdb';shutil.copyfile(writer_path,base)
 c=live.duckdb.connect(str(base),read_only=True)
 try:
  for table,spec in expected.items():
   if signature(c,table)!=spec:raise ValueError('Cold ledger signature differs: '+table)
 finally:c.close()
 if destination.exists() or Path(str(destination)+'.wal').exists():raise ValueError('Generation destination must be new')
 os.replace(base,destination)

def writer(old_input,destination):
 shutil.copy2(old_input,destination);c=live.duckdb.connect(str(destination));c.execute('SET threads=2');changes=live.read_json(destination.parent/'changes.json');pending=live.read_json(destination.parent/'new-clubs.json')
 c.execute('BEGIN')
 try:
  names=[r[0] for r in c.execute('DESCRIBE clubs').fetchall()]
  for club in pending:
   if not c.execute('SELECT 1 FROM clubs WHERE club=?',[club['club']]).fetchone():c.execute('INSERT INTO clubs VALUES('+','.join('?' for _ in names)+')',[club[k] for k in names])
  for mid,row in changes.items():
   exists=c.execute('SELECT count(*) FROM matches WHERE match_id=?',[mid]).fetchone()[0]
   if row is None:c.execute('DELETE FROM matches WHERE match_id=?',[mid])
   elif exists:c.execute('UPDATE matches SET '+','.join(k+'=?' for k in live.FIELDS[1:])+' WHERE match_id=?',[row[k] for k in live.FIELDS[1:]]+[mid])
   else:c.execute('INSERT INTO matches ('+','.join(live.FIELDS)+') VALUES ('+','.join('?' for _ in live.FIELDS)+')',[row[k] for k in live.FIELDS])
  from ledger_repairs import apply_repairs
  live.atomic(destination.parent/'input-repairs.json',apply_repairs(c))
  enabled=destination.parent/'history-enabled.json'
  if enabled.exists() and live.read_json(enabled):
   from brazil_history import apply_history
   live.atomic(destination.parent/'brazil-history.json',apply_history(c))
  c.execute('COMMIT');route_database(destination,connection=c)
  expected={table:signature(c,table) for table in ('matches','clubs','model_route_days')};live.atomic(destination.parent/'input-signatures.json',expected);c.execute('CHECKPOINT')
 except Exception:
  try:c.execute('ROLLBACK')
  except Exception:pass
  raise
 finally:c.close()
if __name__=='__main__':writer(Path(sys.argv[1]),Path(sys.argv[2]))
