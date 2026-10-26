"""Bounded automatic overlap download for the integration run, cached by URL."""
import argparse,json,urllib.request,concurrent.futures,hashlib,time
from pathlib import Path
from urllib.parse import urlencode
from free_sources import years,FOTMOB,ESPN

def main():
 p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);a=p.parse_args();a.cache.mkdir(exist_ok=True,parents=True)
 sources=json.loads((Path(__file__).parents[2]/'config/club_sources.json').read_text())['sources'];urls=[]
 for s in sources:
  pid=s['provider_id']
  if s['provider']=='fotmob':
   f=a.evidence/'responses'/('fotmob_'+pid+'.json')
   if not f.exists():continue
   raw=json.loads(f.read_text())
   if not isinstance(raw,dict):continue
   if (raw.get('details') or {}).get('gender')!='male':continue
   selected=(raw.get('details') or {}).get('selectedSeason')
   for season in raw.get('allAvailableSeasons') or []:
    yy=years(season)
    if season!=selected and yy and min(yy)<=2026 and max(yy)>=2025:urls.append(FOTMOB+'/leagues?id='+pid+'&'+urlencode({'season':season}))
  elif s['provider']=='espn':urls.append(ESPN+'/'+pid+'/scoreboard?dates=2025&limit=1000')
 def fetch(url):
  target=a.cache/(hashlib.sha256(url.encode()).hexdigest()+'.json')
  if target.exists():return {'url':url,'status':'cached'}
  try:
   request=urllib.request.Request(url,headers={'User-Agent':'NFElo-club-updater/2.0','Accept-Encoding':'identity'})
   with urllib.request.urlopen(request,timeout=25) as r:raw=r.read(32*1024*1024)
   data=json.loads(raw);target.write_bytes(raw);return {'url':url,'status':'retrieved','bytes':len(raw)}
  except Exception as e:return {'url':url,'status':'failed','error':str(e)}
 results=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for result in pool.map(fetch,sorted(set(urls))):
   results.append(result)
   if len(results)%30==0:print(len(results),'/',len(set(urls)),flush=True)
 (a.cache/'index.json').write_text(json.dumps(results,indent=2));print('done',len(results),sum(x['status']=='failed' for x in results),flush=True)
if __name__=='__main__':main()
