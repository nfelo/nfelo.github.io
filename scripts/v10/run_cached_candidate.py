"""Replay the real production updater against accepted, reproducible feed input."""
import argparse,json,shutil
from pathlib import Path
from unittest.mock import patch
import v10_live as live

def main():
 p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--integration',type=Path,required=True);a=p.parse_args()
 cfg=live.read_json(a.state/'config.json');cfg.update(full_site=False,free_sources=live.read_json(live.HERE.parents[1]/'config/club_sources.json'));cfg['limitations']=cfg['free_sources']['limitations'];live.atomic(a.state/'config.json',cfg)
 shutil.copy2(a.integration/'state/pending_clubs.json',a.state/'pending_clubs.json')
 obs=live.read_json(a.integration/'observations.json');health=live.read_json(a.integration/'health.json')
 with patch.object(live,'collect',return_value=(obs,health,{'http_requests':0,'unchanged_responses':0})):
  first=live.update(a.state,live.date(2026,10,25));live.atomic(a.integration/'candidate-first.json',first);print('FIRST',json.dumps({k:v for k,v in first.items() if k!='sources'}),flush=True)
  second=live.update(a.state,live.date(2026,10,25));live.atomic(a.integration/'candidate-second.json',second);print('SECOND',json.dumps({k:v for k,v in second.items() if k!='sources'}),flush=True)
  assert second['result']=='no_change' and not second['model_ran']
if __name__=='__main__':main()
