"""Bounded round progress, retry persistence and safe installer updates."""
import sqlite3,unittest
from datetime import date
from unittest.mock import patch
from free_sources import gsa
from wider_sources import collect_gsa,season_links

def page(extra=''):
 return '<div class="gsa-comp-dropdown__list"><a href="https://globalsportsarchive.com/en/soccer/competition/test-2026/1">2026</a>'+extra+'</div><div data-competition_id="1" data-weeks=\'{"100_1":1,"100_2":2,"100_3":3}\'></div>'
def event(mid='one',score='1 : 0'):
 return f'<a data-match_id="{mid}"><span>01.03.2026</span><img src="https://dsg-images.com/clubs/50x50/1.png" alt="logo of A"/><div class="gsa-match-played">{score}</div><img src="https://dsg-images.com/clubs/50x50/2.png" alt="logo of B"/></a>'
class WiderSourcesTests(unittest.TestCase):
 def test_played_scores_and_awards_have_different_lifecycles(self):
  self.assertEqual(gsa(event(),{'kind':'league'})[0]['home_goals'],1)
  self.assertEqual(gsa(event(score='AWD'),{'kind':'league'})[0]['lifecycle'],'unresolved')
 def test_round_backfill_advances_and_retains_prior_results(self):
  db=sqlite3.connect(':memory:');self.addCleanup(db.close)
  class Fetch:
   def __init__(self):self.rounds=[]
   def text(self,url,form=None):
    if form:self.rounds.append(form['activeSubRoundKey']);return event(form['activeSubRoundKey'])
    return page()
  f=Fetch();s=dict(id='gsa-test',provider_id='1',url='https://example/test-2026/1',kind='league',rounds_per_refresh=1);rows=[]
  for _ in range(3):rows=collect_gsa(dict(s),f,date(2026,10,26),db,rows)
  self.assertEqual(f.rounds,['100_1','100_2','100_3']);self.assertEqual(len(rows),3)
 def test_failed_round_is_retried_without_erasing_accepted_rows(self):
  db=sqlite3.connect(':memory:');self.addCleanup(db.close)
  class Fetch:
   def text(self,url,form=None):
    if form:raise OSError('outage')
    return page()
  s=dict(id='gsa-test',provider_id='1',url='https://example/test-2026/1',kind='league',rounds_per_refresh=1);old=gsa(event(),s)
  self.assertEqual(collect_gsa(s,Fetch(),date(2026,10,26),db,old),old)
  self.assertEqual(db.execute('SELECT count(*) FROM gsa_rounds').fetchone()[0],0);self.assertEqual(s['_backfill']['rounds_remaining'],3)
 def test_season_menu_is_scoped_to_the_selected_competition(self):
  extra='<a href="https://globalsportsarchive.com/en/soccer/competition/test-2027/2">2027</a>'
  self.assertEqual(season_links(page(extra))[0][0],2027)
  self.assertEqual(season_links('<nav><a href="/soccer/competition/other-2028/9">2028</a></nav>'),[])
class InstallerTests(unittest.TestCase):
 def setUp(self):
  import install_release
  self.module=install_release;self.files={'example.txt':b'corrected'};self.manifest={'files':{'example.txt':{'base_blob':'old-blob'}}}
 def test_changed_code_stops_before_any_github_write(self):
  calls=[]
  def api(path,method='GET',payload=None):
   calls.append(method)
   return {'':{'default_branch':'main'},'git/ref/heads/main':{'object':{'sha':'parent'}},'git/commits/parent':{'tree':{'sha':'tree'}},'git/trees/tree?recursive=1':{'tree':[{'path':'example.txt','type':'blob','sha':'other-change'}]}}[path]
  with patch.object(self.module,'api',side_effect=api),self.assertRaisesRegex(RuntimeError,'Repository code changed'):self.module.install(self.manifest,self.files)
  self.assertEqual(set(calls),{'GET'})
 def test_concurrent_main_update_is_never_overwritten(self):
  calls=[];refs=[]
  def api(path,method='GET',payload=None):
   calls.append((path,method))
   if path=='git/ref/heads/main':refs.append(path);return {'object':{'sha':'parent' if len(refs)==1 else 'new-data'}}
   return {'':{'default_branch':'main'},'git/commits/parent':{'tree':{'sha':'tree'}},'git/trees/tree?recursive=1':{'tree':[{'path':'example.txt','type':'blob','sha':'old-blob'}]},'git/blobs':{'sha':'blob'},'git/trees':{'sha':'newtree'},'git/commits':{'sha':'newcommit'}}[path]
  with patch.object(self.module,'api',side_effect=api),self.assertRaisesRegex(RuntimeError,'main advanced'):self.module.install(self.manifest,self.files)
  self.assertFalse(any(method=='PATCH' for _,method in calls))
if __name__=='__main__':unittest.main()
