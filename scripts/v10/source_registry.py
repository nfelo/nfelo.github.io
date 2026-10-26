"""Versioned scope rules, refreshed catalogues, stable provider competition IDs."""
import json,re
from pathlib import Path
from free_sources import eligible
TOP=set('260 516 112 118 113 38 262 10443 263 40 144 267 268 270 9986 273 120 274 121 252 136 122 46 246 519 335 47 248 250 51 53 439 54 522 135 336 337 212 215 9478 8983 523 524 126 127 55 223 225 529 226 228 229 249 8985 230 231 232 530 57 8870 533 129 59 9039 199 131 196 61 535 189 63 536 64 182 461 176 173 537 9080 87 67 69 9066 8984 544 71 441 538 130 161 540 339 9088 116'.split())
SECOND=set('8965 8938 119 264 8814 9096 9126 9137 9125 9100 253 85 48 251 110 146 8815 9117 216 8982 10056 9372 218 128 86 8974 8976 111 203 197 185 11030 9113 338 10721 123 8973 9116 140 168 163 9498 165 8972 9122'.split())
LOWER={x:3 for x in '9213 8971 239 108 8969 8970 208 10226 147 9136 9195 204 8935 9112 9123 124 9537 8968 169 9296'.split()}
LOWER.update({x:4 for x in '9464 240 109 512 205 125 9138'.split()});LOWER.update({'117':5,'8944':6,'8947':7,'9545':5,'241':5,'285':5})
STATES=set('10290 10272 10274 10291 10273 10244 9483'.split())
INTERNATIONAL=set('42 73 10216 10611 10613 10615 9470 525 9469 10622 526 9468 10619 9467 45 299 10623 491 297 9682 10043 9875 78 10703 11527'.split())
OUTSIDE=set('10844 10840 11157 10282 10084 11499 10075'.split())
NEUTRAL_FINAL=set('42 73 10216 9470 525 78 10703'.split())
def kind(name,pid,provider):
 if provider=='fotmob':
  if pid in TOP:return 'league',1
  if pid in SECOND:return 'league',2
  if pid in LOWER:return 'league',LOWER[pid]
  if pid in STATES:return 'state',None
  if pid in INTERNATIONAL:return ('global' if pid=='78' else 'intercontinental' if pid=='10703' else 'super_cup' if pid in ('9467','491','9875') else 'continental'),None
  if pid in OUTSIDE:return None,None
 if provider=='espn' and re.search(r'\.[1-4]$',pid):return 'league',int(pid[-1])
 if provider=='espn' and pid.split('.')[0] in ('uefa','afc','caf','conmebol','concacaf','fifa'):
  return ('global' if 'club' in pid and 'fifa' in pid else 'super_cup' if 'super' in pid or 'recopa' in pid else 'continental'),None
 if re.search(r'super|community shield|recopa|campe[oó]n|trofeo',name,re.I):return 'super_cup',None
 if re.search(r'qualification|play.?off|relegation',name,re.I):return 'playoff',None
 if re.search(r'cup|copa|coupe|pokal|puchar|ta[cç]a|kup|trophy|troph[eé]e|norgesmesterskapet|løgmanssteypið',name,re.I):return 'domestic_cup',None
 return None,None

def from_catalogue(catalogue):
 rows=[];seen=set()
 for group in catalogue.get('countries',[])+catalogue.get('international',[]):
  for item in group.get('leagues',[]):
   pid=str(item['id']);name=item['name']
   if pid in seen or not eligible(name) or pid in OUTSIDE:continue
   if group in catalogue.get('international',[]) and pid not in INTERNATIONAL:continue
   seen.add(pid);k,t=kind(name,pid,'fotmob')
   if not k:continue
   rows.append(dict(id='fotmob-'+pid,provider='fotmob',provider_id=pid,competition=name,country=group['name'] if group in catalogue.get('countries',[]) else None,kind=k,tier=t,neutral_final=pid in NEUTRAL_FINAL,neutral_all=pid in ('78','10703'),refresh_hours=20))
 return rows

def initial(evidence):
 p=Path(evidence);rows=from_catalogue(json.loads((p/'fotmob_catalog.json').read_text()))
 for x in json.loads((p/'coverage_results.json').read_text())['results']:
  if x['provider']!='espn' or x['status']!='retrieved' or not eligible(x['name']):continue
  pid=x['provider_competition_id'];k,t=kind(x['name'],pid,'espn')
  if k:rows.append(dict(id='espn-'+pid,provider='espn',provider_id=pid,competition=x['name'],country=x.get('country'),kind=k,tier=t,neutral_final=pid in ('uefa.champions','uefa.europa','uefa.europa.conf'),neutral_all=pid=='fifa.cwc',refresh_hours=20))
 for slug in 'acreano alagoano amapaense amazonense baiano brasiliense capixaba carioca catarinense cearense gaucho goiano maranhense matogrossense mineiro paraense paraibano paranaense paulista pernambucano piauiense potiguar rondoniense roraimense sergipano sul-matogrossense tocantinense'.split():
  rows.append(dict(id='soccerway-brazil-'+slug,provider='soccerway',provider_id='brazil/'+slug,url='https://www.soccerway.com/brazil/'+slug+'/results/',competition=slug.title(),country='Brazil',kind='state',tier=None,refresh_hours=72))
 return {'schema':1,'discovery_days':7,'sources':rows,'limitations':['Modern feeds supplement the historical archive; a catalogue listing alone is not counted as live coverage.','Unresolved identities, score phases and incomplete pages are held individually or retain the previous source snapshot.','GSA and OFC routes remain to be activated; historical world coverage is incomplete.']}
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--evidence',required=True);p.add_argument('--output',required=True);a=p.parse_args();out=initial(a.evidence);Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(len(out['sources']))
