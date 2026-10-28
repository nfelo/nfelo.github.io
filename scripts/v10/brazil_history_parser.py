"""Dated RSSSF Brazil schedules, preserving state scope and actual years."""
from datetime import date
import re,unicodedata
from lxml import html
MONTHS={x:i for i,names in enumerate([
 ['jan','january','janeiro'],['feb','february','fev','fevereiro'],['mar','march','marco'],
 ['apr','april','abr','abril'],['may','mai','maio'],['jun','june','junho'],['jul','july','julho'],
 ['aug','august','ago','agosto'],['sep','sept','september','set','setembro'],
 ['oct','october','out','outubro'],['nov','november','novembro'],['dec','december','dez','dezembro']],1) for x in names}
def norm(value):return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower()).strip()
def year_number(value,season):
 n=int(value);return n if n>99 else (season//100)*100+n
def dates(text,season):
 text=text.strip('[] <>').strip()
 if re.search(r'\d\s*[-–]\s*\d',text):return []
 shared=re.search(r'[/,]\s*(\d{4}|\d{2})\s*$',text);year=year_number(shared[1],season) if shared else season
 parts=re.split(r'\s+(?:and|e)\s+|\s*&\s*',text,flags=re.I);result=[];month=None
 for part in parts:
  numeric=re.fullmatch(r'(\d{1,2})[./](\d{1,2})[./](\d{2,4})',part.strip())
  english=re.fullmatch(r'([A-Za-zçé]+)\s+(\d{1,2})(?:[/,]\s*(\d{2,4}))?',part.strip())
  european=re.fullmatch(r'(\d{1,2})[/ .-]([A-Za-zçé]+)(?:[/ ,.-]+(\d{2,4}))?',part.strip())
  short=re.fullmatch(r'(\d{1,2})(?:[/,]\s*(\d{2,4}))?',part.strip())
  if numeric:day,month,y=int(numeric[1]),int(numeric[2]),year_number(numeric[3],season)
  elif english:month=MONTHS.get(norm(english[1]));day=int(english[2]);y=year_number(english[3],season) if english[3] else year
  elif european:day=int(european[1]);month=MONTHS.get(norm(european[2]));y=year_number(european[3],season) if european[3] else year
  elif short and month:day=int(short[1]);y=year_number(short[2],season) if short[2] else year
  else:return []
  if not month or y<season or y>season+1:return []
  try:result.append(date(y,month,day).isoformat())
  except ValueError:return []
 return result
DATE_PREFIX=re.compile(r'^(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}/[A-Za-zçé]+(?:/\d{2,4})?)\s+(.*)$')
SCORE=re.compile(r'(?<!\d)(\d{1,2})\s*[-xX–]\s*(\d{1,2})(?!\d)')
def parse(raw,route):
 tree=html.fromstring(re.sub(br'</html\s*>',b'',raw,flags=re.I))
 for element in tree.xpath('//script|//style'):element.drop_tree()
 for element in tree.xpath('//br'):element.tail='\n'+(element.tail or '')
 lines=tree.text_content().replace('\xa0',' ').splitlines();current=[];rows=[];held=[];seen=set()
 for index,original in enumerate(lines):
  line=original.strip()
  if not line:continue
  if re.search(r'^(?:about this document|details on|final (?:table|standings)|classifica|source:)',line,re.I):current=[]
  prefix=DATE_PREFIX.match(line)
  if prefix:daylist=dates(prefix[1],route['season']);body=prefix[2]
  else:
   header=re.match(r'^\[([^]]+)\](?:\s*-.*)?$',line);exact=dates(line,route['season']) if not SCORE.search(line) else []
   date_header=header and re.match(r'^(?:\d|[A-Za-z]+\s+\d)',header[1])
   if date_header or exact:
    current=dates(header[1],route['season']) if header else exact;continue
   daylist=current;body=line
  matches=list(SCORE.finditer(body))
  if not matches:continue
  home=body[:matches[0].start()].strip();away=body[matches[-1].end():].strip()
  if (not away or norm(away) in ('sao','xv','portugues')) and prefix and index+1<len(lines):
   following=lines[index+1].strip()
   if re.fullmatch(r'[A-Za-zÀ-ÿ .()\-/]+',following):away=(away+' '+following).strip()
  if not home or not away or home[0].isdigit() or home.startswith('[') or not daylist:continue
  if len(matches)!=len(daylist):held.append({'line':index+1,'text':line,'reason':'date_score_count_mismatch'});continue
  if re.search(r'\b(?:awd|awarded|abandon\w*|cancel\w*|penalties|pens|suspens\w*|suspended|anulad\w*|interrupted|interromp\w*|conclu\w*|encerrad\w*)\b|W\.O\.',body,re.I):
   held.append({'line':index+1,'text':line,'reason':'nonstandard_score'});continue
  note='';annotation=re.search(r'\s+\[|\s+\((?:aet|in |[0-9])',away,re.I)
  if annotation:away,note=away[:annotation.start()].strip(),away[annotation.start():]
  for leg,(day,score) in enumerate(zip(daylist,matches)):
   h,a,hg,ag=home,away,int(score[1]),int(score[2])
   if leg==1:h,a,hg,ag=a,h,ag,hg
   key=(day,norm(h),norm(a),hg,ag)
   if key in seen:continue
   seen.add(key);rows.append(dict(date=day,home_name=h,away_name=a,home_goals=hg,away_goals=ag,season=route['season'],scope=route['scope'],competition=route['competition'],kind=route['kind'],source='rsssf-brasil',source_ref=route['url']+'#line-'+str(index+1),neutral=bool(re.search(r'neutral',note,re.I)),status='E' if re.search(r'\baet\b',note,re.I) else 'F'))
 return rows,held
