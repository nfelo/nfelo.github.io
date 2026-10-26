"""One physical match, one ledger row; conflicts retain the published result."""
from collections import defaultdict
from datetime import date
import v10_live as live
CORE=('home_goals','away_goals','kind','status','neutral','leg','aggregate_before_home','aggregate_after_home')
def reconcile(input_path,observations,as_of,pending_clubs=()):
 c=live.duckdb.connect(str(input_path),read_only=True)
 clubs={r['club']:r for r in live.query(c,'SELECT * FROM clubs')}
 for r in pending_clubs:
  if r['club'] in clubs and r!=clubs[r['club']]:raise ValueError('pending_club_identity_conflict')
  clubs[r['club']]=r
 dates=[e.get('date') for _,e in observations if e.get('date')]
 first=min(dates,default=str(as_of));ledger=live.query(c,'SELECT * FROM matches WHERE day>=?',[first]);c.close()
 ids={r['match_id']:r for r in ledger};pairs=defaultdict(list);days=defaultdict(set)
 for r in ledger:pairs[r['day'],r['home'],r['away']].append(r);days[r['day']].update((r['home'],r['away']))
 groups=defaultdict(list);fixtures={};changes={};exceptions=[];unchanged=0;withdrawals=[]
 def held(source,e,reason,old=False):exceptions.append(dict(source=source,id=e['id'],reason=reason,date=e.get('date'),home=e.get('home_name'),away=e.get('away_name'),previous_result_retained=old,competition=e.get('competition'),competition_key=e.get('competition_key'),season=e.get('season')))
 for source,e in observations:
  mid='live_'+live.digest((source+':'+e['id']).encode())[:27];life=e.get('lifecycle')
  if life in ('fixture','withdrawn','in_progress'):
   withdrawals.append((source,e,mid))
   if life=='fixture' and e.get('date'):fixtures.setdefault((e['date'],e.get('home'),e.get('away')),dict(e,source_key=source))
   continue
  try:
   if life=='unresolved':raise ValueError(';'.join(e.get('reasons') or ['unresolved_source_record']))
   row=live.model_record(source,e,clubs,as_of);groups[row['day'],row['home'],row['away']].append((source,e,row))
  except (KeyError,TypeError,ValueError) as error:held(source,e,str(error),mid in ids)
 reserved=defaultdict(set)
 for key,items in sorted(groups.items()):
  signatures={tuple(row[x] for x in CORE) for _,_,row in items};existing=pairs[key]
  if len(signatures)>1:
   for source,e,_ in items:held(source,e,'cross_source_result_conflict',bool(existing))
   continue
  source,e,row=items[0];mid=row['match_id']
  if len(existing)>1:
   held(source,e,'existing_match_ambiguous',True);continue
  if existing:
   old=existing[0]
   # The event's date/participants and competition kind identify a physical
   # match. Preserve the historical ID and canonical competition on agreement.
   if all(old[k]==row[k] for k in CORE):unchanged+=len(items);continue
   owners={s+':'+x['id'] for s,x,_ in items}
   if old['source_ref'] not in owners and len({s.split('-')[0] for s,_,_ in items})<2:
    held(source,e,'existing_match_conflict',True);continue
   mid=old['match_id'];row.update(match_id=mid,competition_key=old['competition_key'],competition=old['competition'])
  elif {row['home'],row['away']} & (days[row['day']]|reserved[row['day']]):
   held(source,e,'same_day_order_requires_resolution');continue
  changes[mid]=row;reserved[row['day']].update((row['home'],row['away']));unchanged+=len(items)-1
 for source,e,mid in withdrawals:
  old=ids.get(mid)
  if old and (old['day'],old['home'],old['away']) not in groups:changes[mid]=None
 # A completed result wins over another provider's obsolete fixture listing.
 fixtures=[r for key,r in fixtures.items() if (date.fromisoformat(key[0]),key[1],key[2]) not in groups]
 return changes,fixtures,exceptions,unchanged
