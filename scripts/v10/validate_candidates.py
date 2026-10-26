"""Finite chronological comparison; no search against the test period."""
import argparse,time
from pathlib import Path
import v10_live as live

def main():
 p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 config=live.load_club_config(live.HERE/'engine/club_model.json')
 plain=dict(config,k_factor=20.,country_share=0.,confederation_share=0.,tier_share=0.,tier_gap=0.,margin_scale=0.,club_retention=1.,country_retention=1.,confederation_retention=1.,tier_retention=1.,aggregate_floor=1.,extra_time_weight=1.,penalty_weight=1.,uncertainty_penalty=0.,competition_weights={k:1. for k in config['competition_weights']})
 output={'input_sha256':live.file_sha(a.input),'engine_sha256':live.file_sha(live.HERE/'engine/club_model.py'),'warmup_start':'2000-01-01','selection_rule':'Fixed inherited hierarchical model versus fixed plain Elo control; validation selects, test reported once. No parameter search.','candidates':{}}
 for name,cfg in [('hierarchical',config),('plain_elo',plain)]:
  output['candidates'][name]={'config':cfg,'periods':{}}
  for period,start,end in [('validation','2018-01-01','2022-12-31'),('test','2023-01-01','2026-10-24')]:
   t=time.monotonic();result=live.run_club_model(a.input,cfg,write_tables=False,replay_from='2000-01-01',evaluation_start=start,evaluation_end=end)
   output['candidates'][name]['periods'][period]={'start':start,'end':end,'seconds':round(time.monotonic()-t,2),**result}
   live.atomic(a.output,output);print(name,period,result['metrics']['all'],flush=True)
if __name__=='__main__':main()
