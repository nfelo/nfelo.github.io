"""Exercise production parsers, identities and reconciliation on saved responses."""
import argparse,gzip,json,sqlite3,hashlib
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from collections import Counter
import v10_live as live
import free_update
class SavedFeeds:
 def __init__(self,path,overlap=None):self.path=path;self.overlap=overlap;self.requests=self.unchanged=0
 def get(self,url):
  self.requests+=1
  if self.overlap:
   archive=self.overlap/(hashlib.sha256(url.encode()).hexdigest()+'.json')
   if archive.exists():return json.loads(archive.read_text())
   if 'season=' in url or 'dates=2025' in url:raise ValueError('overlap_not_cached')
  q=parse_qs(urlparse(url).query)
  if 'allLeagues' in url:name='fotmob_catalog.json';p=self.path/name
  elif '/leagues?' in url:
   pid=q['id'][0];p=self.path/'responses'/('fotmob_'+pid+'.json')
  elif '/scoreboard?' in url:p=self.path/'responses'/('espn_'+url.split('/soccer/')[1].split('/')[0]+'.json')
  else:raise ValueError('not_in_saved_evidence:'+url)
  value=json.loads(p.read_text())
  if not self.overlap and 'details' in value:value['allAvailableSeasons']=[value['details'].get('selectedSeason')]
  return value
 def text(self,url):
  self.requests+=1;slug=url.split('soccerway.com/')[1].removesuffix('/results/').replace('/','_');return (self.path/'soccerway'/(slug+'.html')).read_text()
def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--overlap',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=True,parents=True)
 state=a.output/'state';state.mkdir(exist_ok=True);live.atomic(state/'current.json',{'input':str(a.input.resolve())})
 # Seed the old provider bindings, retaining their stored evidence.
 seed=live.HERE.parents[1]/'club-state/observations.sqlite.gz'
 if seed.exists() and not (state/'observations.sqlite').exists():(state/'observations.sqlite').write_bytes(gzip.decompress(seed.read_bytes()))
 cfg=live.read_json(live.HERE.parents[1]/'config/club_sources.json');cfg.update(discover=False,daily=False)
 obs,health,transport=free_update.collect(state,cfg,live.date(2026,10,25),SavedFeeds(a.evidence,a.overlap),bootstrap=bool(a.overlap))
 live.atomic(a.output/'health.json',health);live.atomic(a.output/'observations.json',obs)
 changes,fixtures,held,same=live.reconcile(a.input,obs,live.date(2026,10,25),live.read_json(state/'pending_clubs.json'));live.atomic(a.output/'changes.json',changes);live.atomic(a.output/'exceptions.json',held)
 countries=set();kinds=Counter();sources=Counter()
 for r in changes.values():
  if r:kinds[r['kind']]+=1;sources[r['source_ref'].split(':',1)[0]]+=1
 report={'scope':'Saved current-season/2026 snapshots plus '+str(len(list(a.overlap.glob('*.json')))-1 if a.overlap else 0)+' fetched overlapping seasons; detail gaps remain held','observations':len(obs),'normalised_results':sum(e['lifecycle']=='result' for _,e in obs),'new_or_corrected':len(changes),'fixtures':len(fixtures),'held':len(held),'unchanged':same,'changes_by_kind':dict(kinds),'sources_with_changes':len(sources),'source_statuses':dict(Counter(h['status'] for h in health)),'holds':dict(Counter(x['reason'].split(':')[0] for x in held)),**transport}
 live.atomic(a.output/'report.json',report);print(json.dumps(report,indent=2))
if __name__=='__main__':main()
