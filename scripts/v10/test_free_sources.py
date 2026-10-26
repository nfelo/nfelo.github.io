"""Behavioral regressions for source phases, cache persistence and comparisons."""
from datetime import date
from pathlib import Path
import copy,json,tempfile,unittest
from unittest.mock import patch
import v10_live as live
from free_sources import fotmob,espn,soccerway,eligible
from club_model import ClubRatingModel
from test_live import PipelineTest

class ParsingTests(unittest.TestCase):
 def payload(self):
  return {'details':{'id':42,'name':'Champions League','gender':'male','selectedSeason':'2025/2026'},'fixtures':{'allMatches':[{'id':'b','home':{'id':2,'name':'B'},'away':{'id':1,'name':'A'},'roundName':'Round of 16','status':{'utcTime':'2026-03-12T20:00:00Z','finished':True,'scoreStr':'2 - 0','reason':{'short':'Pen'}}}]},'playoff':{'rounds':[{'matchups':[{'bestOf':2,'stage':'round16','matches':[{'matchId':'a','home':{'id':1},'away':{'id':2},'status':{'utcTime':'2026-03-05T20:00:00Z','scoreStr':'2 - 0'}},{'matchId':'b','home':{'id':2},'away':{'id':1},'status':{'utcTime':'2026-03-12T20:00:00Z','scoreStr':'2 - 0'}}]}]}]}}
 def test_penalties_do_not_erase_second_leg_win(self):
  r=fotmob(self.payload(),{'provider_id':'42'})[0]
  self.assertEqual((r['leg'],r['aggregate_before_home'],r['aggregate_after_home']),(2,-2,0))
  self.assertEqual(ClubRatingModel._score(r['home_goals'],r['away_goals'],r['status']),1.)
 def test_wrong_gender_or_competition_rejected(self):
  p=self.payload();p['details']['gender']='female'
  with self.assertRaisesRegex(ValueError,'scope'):fotmob(p,{'provider_id':'42'})
  with self.assertRaisesRegex(ValueError,'identity'):fotmob(self.payload(),{'provider_id':'73'})
 def test_future_completed_is_not_a_fixture(self):
  p=self.payload();p['fixtures']['allMatches'][0]['status']['utcTime']='2027-01-01T12:00:00Z'
  r=fotmob(p,{'provider_id':'42'})[0];self.assertEqual(r['lifecycle'],'result')
  with self.assertRaisesRegex(ValueError,'future_completed'):live.model_record('fm',dict(r,date='2027-01-01'),{},date(2026,10,25))
 def test_incomplete_page_never_claims_full_coverage(self):
  raw="cjs.initialFeeds['results'] = { data: `AA÷one¬AD÷1774141200¬PX÷a¬PY÷b¬AE÷A¬AF÷B¬AG÷1¬AH÷0¬AC÷3`, allEventsCount: 2 }"
  with self.assertRaisesRegex(ValueError,'incomplete_pagination'):soccerway(raw,{})
 def test_no_youth_or_friendly_scope(self):
  for name in ('Premier League 2','U21 League','Club Friendlies','Primavera'):self.assertFalse(eligible(name))

class IntegrationRegressions(PipelineTest):
 def test_new_club_admitted_from_repeated_resolved_opponents(self):
  from club_identity import Resolver
  db=live.state_db(self.state);resolver=Resolver(self.input,db)
  source=dict(id='fotmob-test',provider='fotmob',country='England',kind='league',tier=1,competition='Test League')
  rows=[dict(id=str(i),provider='fotmob',lifecycle='result',kickoff='2026-01-'+str(10+i)+'T12:00:00Z',season=2026,home_id='new',home_name='Garnet Town',away_id=str(i),away_name='Test Club '+str(i),home_goals=1,away_goals=0,status='F',leg=0,round_name='1') for i in (0,1)]
  resolver.prepare([(source,rows)],date(2026,1,31));self.assertEqual(resolver.bindings['fotmob','new'],4)
  converted=[resolver.convert(source,r,date(2026,1,31)) for r in rows];self.assertTrue(all(r['lifecycle']=='result' for r in converted),converted);pending=[resolver.clubs[4]];resolver.close();db.close()
  cfg=live.read_json(self.state/'config.json');cfg['free_sources']={'sources':[]};live.atomic(self.state/'config.json',cfg);live.atomic(self.state/'pending_clubs.json',pending)
  with patch.object(live,'collect',return_value=([('fotmob-test',r) for r in converted],[],{'http_requests':0,'unchanged_responses':0})):
   result=self.run_update();self.assertEqual(result['matches'],6);self.assertEqual(result['exceptions'],0)
 def test_append_resumes_and_matches_full_replay(self):
  self.responses['/a']['events']=[self.event()];self.run_update()
  self.responses['/a']['events'].append(self.event('later',date='2026-01-12',home=2,away=3));self.run_update()
  current=self.current();path=self.state/current['model'];report=live.read_json(path.parent/'model_run.json');self.assertIsNotNone(report['resumed_from'])
  other=self.state/'full-replay.duckdb';live.run_club_model(self.state/current['input'],live.load_club_config(live.HERE/'engine/club_model.json'),output_database=other)
  c=live.duckdb.connect(str(path),read_only=True);c.execute("ATTACH '"+str(other)+"' AS full_model (READ_ONLY)")
  for table in ('rated_matches','current_club_ratings','year_openings'):
   self.assertEqual(c.execute('SELECT count(*) FROM ((SELECT * FROM '+table+') EXCEPT ALL (SELECT * FROM full_model.'+table+'))').fetchone()[0],0)
  c.close()
 def test_agreeing_sources_insert_once(self):
  self.responses['/a']['events']=[self.event()];self.responses['/b']['events']=[self.event('other')]
  r=self.run_update();self.assertEqual(r['matches'],5);self.assertEqual(r['exceptions'],0)
 def test_conflicting_sources_do_not_publish_either(self):
  self.responses['/a']['events']=[self.event()];self.responses['/b']['events']=[self.event('other',home_goals=3)]
  r=self.run_update();self.assertEqual(r['matches'],4);self.assertEqual(r['exceptions'],2)
 def test_model_version_change_replays_without_new_results(self):
  self.run_update();cur=self.current();cur['model_identity']='old';live.atomic(self.state/'current.json',cur)
  r=self.run_update();self.assertTrue(r['model_ran']);self.assertTrue(r['model_changed']);self.assertEqual(self.run_update()['result'],'no_change')
 def test_aggregate_penalties_and_wrong_aggregate(self):
  self.responses['/a']['events']=[self.event(status='P',leg=2,tie_key='tie',aggregate_before_home=-2,aggregate_after_home=0)]
  r=self.run_update();self.assertEqual(r['matches'],5);self.assertEqual(r['exceptions'],0)
  self.responses['/a']['events'][0]['aggregate_before_home']=-3;r=self.run_update();self.assertEqual(r['matches'],5);self.assertEqual(r['exceptions'],1)
 def test_fixed_reference_tier_has_no_extra_uncertainty(self):
  c=live.duckdb.connect(str(self.input),read_only=True)
  model=ClubRatingModel(c,live.load_club_config(live.HERE/'engine/club_model.json'),write_tables=False)
  model.replay();self.assertEqual(model.component_standard_errors(0,date(2026,1,31).toordinal())[1],0.)
  self.assertEqual(model.public_rating(0,date(2026,1,31).toordinal()),model.mean(0));c.close()
if __name__=='__main__':unittest.main()

class ArchiveTests(unittest.TestCase):
 def test_unavailable_archive_keeps_current_results(self):
  from free_sources import load_route
  source={'provider':'fotmob','provider_id':'42'};payload=ParsingTests().payload();payload['allAvailableSeasons']=['2025/2026','2024/2025']
  class Fetch:
   def get(self,url):
    if 'season=' in url:raise OSError('archive unavailable')
    return payload
  rows=load_route(source,Fetch(),date(2026,10,25),bootstrap=True)
  self.assertEqual(len(rows),1);self.assertEqual(source['_warnings'][0]['season'],'2024/2025')
 def test_request_must_return_requested_season(self):
  from free_sources import load_route
  source={'provider':'fotmob','provider_id':'42'};payload=ParsingTests().payload();payload['allAvailableSeasons']=['2025/2026','2024/2025']
  class Fetch:
   def get(self,url):return payload
  rows=load_route(source,Fetch(),date(2026,10,25),bootstrap=True)
  self.assertEqual(len(rows),1);self.assertIn('requested_season_not_returned',source['_warnings'][0]['error'])

class PublicationReferenceTests(unittest.TestCase):
 def test_common_reference_change_leaves_forecasts_unchanged(self):
  from club_model import three_way_probabilities
  cfg={'base_rating':1500.,'publication_reference':'fixed_base'}
  model=ClubRatingModel.__new__(ClubRatingModel);model.config=cfg;model.country_rating=[150.,-50.];model.country_confederation=['Europe','Africa'];model.confederation_index={'Europe':0,'Africa':1};model.confederation_rating=[20.,-40.]
  anchor=model._publication_anchor();self.assertEqual(anchor,170.)
  model.country_rating=[x+500 for x in model.country_rating];self.assertEqual(model._publication_anchor(),670.)
  self.assertEqual(three_way_probabilities(1800.-1700.,.285),three_way_probabilities((1800.-anchor)-(1700.-anchor),.285))
