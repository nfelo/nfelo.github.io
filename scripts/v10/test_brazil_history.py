import unittest
from brazil_history_parser import parse,dates
from brazil_history import apply_history,load_history
import test_model_structure as support
class BrazilHistoryTests(unittest.TestCase):
 def route(self):return dict(season=1962,scope='SP',competition='Campeonato Paulista',kind='state',url='https://rsssfbrasil.com/tablessz/sp1962.htm')
 def test_two_legs_use_actual_year_and_reverse_second_venue(self):
  self.assertEqual(dates('Mar 19 and 31/63',1962),['1963-03-19','1963-03-31']);self.assertEqual(dates('Aug 7-9',1962),[])
  rows,held=parse(b'<pre>[Mar 19 and 31/63]\nSantos 4-3 1-3 Botafogo\n[Apr 2/63]\nBotafogo 0-5 Santos</pre>',dict(self.route(),scope='BR',kind='domestic_cup'))
  self.assertFalse(held);self.assertEqual([(r['date'],r['home_name'],r['home_goals'],r['away_goals']) for r in rows],[('1963-03-19','Santos',4,3),('1963-03-31','Botafogo',3,1),('1963-04-02','Botafogo',0,5)])
 def test_scorer_notes_preserve_date_for_remaining_matches(self):
  rows,_=parse(b'<pre>[Aug 7]\nSantos 2-0 Bahia\n [Pele (2)]\nPalmeiras 1-0 Portuguesa\n [Cesar]\n</pre>',self.route());self.assertEqual(len(rows),2);self.assertTrue(all(r['date']=='1962-08-07' for r in rows))
 def test_malformed_html_and_wrapped_opponents(self):
  rows,_=parse(b'<html><head></html></head><body><pre>09/06/1962 Guarani 5 x 1\nJabaquara\n10/06/1962 Santos 1 x 0 Sao\nPaulo</pre></body>',self.route());self.assertEqual([r['away_name'] for r in rows],['Jabaquara','Sao Paulo'])
 def test_ambiguous_dates_and_unplayed_scores_are_excluded(self):
  rows,held=parse(b'<pre>[Aug 7-9]\nSantos 2-0 Bahia\n10/Aug Santos 1-0 Bahia (match cancelled)\n11/Aug Santos 1-0 Bahia (W.O.)</pre>',self.route());self.assertEqual(rows,[]);self.assertEqual(len(held),2)
 def fixture(self):
  helper=support.ModelStructureTests();c=helper.connection();self.addCleanup(c.close)
  clubs=[dict(code='c',name='C',country='brazil',existing=True),dict(code='new',name='New historical club (SP)',country='brazil',scope='SP',existing=False)]
  row=dict(match_id='history',date='1962-08-07',season=1962,scope='SP',competition='Campeonato Paulista',kind='state',home_code='c',away_code='new',home_name='C',away_name='New',home_goals=2,away_goals=0,neutral=False,status='F',source_ref='https://rsssfbrasil.com/example')
  return c,dict(clubs=clubs,matches=[row])
 def test_import_is_idempotent_dense_and_preserves_later_correction(self):
  c,p=self.fixture();r=apply_history(c,p);second=apply_history(c,p);self.assertEqual((r['added'],r['new_clubs']),(1,1));self.assertEqual(second['added'],0);self.assertEqual(c.execute('SELECT count(*),max(club)+1 FROM clubs').fetchone(),(4,4))
  c.execute('UPDATE matches SET home_goals=3');apply_history(c,p);self.assertEqual(c.execute('SELECT home_goals FROM matches').fetchone()[0],3)
 def test_conflicting_rows_are_both_held(self):
  c,p=self.fixture();p['matches'].append(dict(p['matches'][0],match_id='different',home_goals=4));r=apply_history(c,p);self.assertEqual((r['added'],r['new_clubs'],len(r['held'])),(0,0,2))
 def test_preexisting_reverse_order_is_not_duplicated(self):
  c,p=self.fixture();apply_history(c,p);c.execute("UPDATE matches SET match_id='prior',home=3,away=2,home_goals=0,away_goals=2");r=apply_history(c,p);self.assertEqual((r['added'],r['already_present']),(0,1))
 def test_paulista_1962_dated_match_totals_and_state_identity(self):
  rows=[r for r in load_history()['matches'] if r['scope']=='SP' and r['season']==1962];self.assertEqual(len(rows),240)
  selected=[r for r in rows if 'c13a9c5ee7aa1' in (r['home_code'],r['away_code'])];scores=[(r['home_goals'],r['away_goals']) if r['home_code']=='c13a9c5ee7aa1' else (r['away_goals'],r['home_goals']) for r in selected]
  # Sum the dated score lines. The source's summary table disagrees with its
  # own fixtures; do not alter played scores to force that summary to match.
  self.assertEqual((len(scores),sum(h>a for h,a in scores),sum(h==a for h,a in scores),sum(h<a for h,a in scores),sum(h for h,a in scores),sum(a for h,a in scores)),(30,23,5,2,102,31))
  for r in rows:
   for side in ('home','away'):
    if r[side+'_name']=='Botafogo':self.assertEqual(r[side+'_code'],'c4af3c1a50ce4')
if __name__=='__main__':unittest.main()
