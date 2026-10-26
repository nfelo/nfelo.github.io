#!/usr/bin/env python3
"""Update the independent club section in an installed repository."""
import argparse,json,os,shutil,tempfile
from pathlib import Path
import v10_live as live
import state_pack

def main():
 p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2]);p.add_argument('--as-of',type=live.date.fromisoformat);p.add_argument('--state',type=Path);a=p.parse_args()
 repo=a.repo.resolve();state=a.state or repo/'.v10-runtime';bundle=repo/'club-state'
 if not (state/'current.json').is_file():
  if state.exists():raise RuntimeError('Incomplete runtime exists; rename it before retrying')
  state_pack.hydrate(bundle,state,repo/'public')
 cfg=live.read_json(state/'config.json');cfg['free_sources']=live.read_json(repo/'config/club_sources.json');cfg['limitations']=cfg['free_sources']['limitations'];live.atomic(state/'config.json',cfg)
 report=live.update(state,a.as_of);current=live.read_json(state/'current.json');source=state/current['site']/'clubs'
 if not (source/'data/meta.json').is_file():raise RuntimeError('Full club export did not complete')
 if report['result']!='no_change':
  staging=repo/'public/.v10-clubs-next';backup=repo/'public/.v10-clubs-previous'
  if staging.exists():shutil.rmtree(staging)
  shutil.copytree(source,staging)
  if backup.exists():shutil.rmtree(backup)
  destination=repo/'public/clubs'
  if destination.exists():os.replace(destination,backup)
  try:os.replace(staging,destination)
  except Exception:
   if backup.exists():os.replace(backup,destination)
   raise
  if backup.exists():shutil.rmtree(backup)
 state_pack.pack(state,bundle)
 live.atomic(repo/'V10_LAST_UPDATE.json',report);print(json.dumps(report,indent=2))
if __name__=='__main__':main()
