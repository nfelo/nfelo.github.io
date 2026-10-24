"""HTTP-to-site integration, including no-change, correction and rollback."""
from datetime import date
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import os,tempfile,threading,unittest
from unittest.mock import patch
from pathlib import Path
import v10_live as live

class PipelineTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.responses={}
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    value=cls.responses.get(self.path)
    if isinstance(value,int) or value is None:self.send_error(value or 404);return
    raw=live.encoded(value);etag='"'+live.digest(raw)+'"'
    if self.headers.get('If-None-Match')==etag:self.send_response(304);self.end_headers();return
    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('ETag',etag);self.end_headers();self.wfile.write(raw)
   def log_message(self,*args):pass
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=cls.server.serve_forever,daemon=True).start()
  cls.base='http://127.0.0.1:'+str(cls.server.server_port);cls.input=cls.root/'seed.duckdb';cls.model=cls.root/'seed-model.duckdb'
  c=live.duckdb.connect(str(cls.input))
  c.execute('CREATE TABLE clubs(club INTEGER,code VARCHAR,name VARCHAR,country VARCHAR,country_name VARCHAR,country_code VARCHAR,continent VARCHAR,identity VARCHAR,resolution VARCHAR)')
  for i in range(4):c.execute('INSERT INTO clubs VALUES(?,?,?,?,?,?,?,?,?)',[i,'test-'+str(i),'Test Club '+str(i),'england','England','ENG','Europe','test','integration fixture'])
  types=['VARCHAR','DATE','INTEGER','INTEGER','INTEGER','SMALLINT','SMALLINT','VARCHAR','VARCHAR','VARCHAR','SMALLINT','SMALLINT','BOOLEAN','BOOLEAN','VARCHAR','SMALLINT','VARCHAR','VARCHAR','VARCHAR','VARCHAR','SMALLINT','SMALLINT']
  c.execute('CREATE TABLE matches('+','.join(n+' '+t for n,t in zip(live.FIELDS,types))+')')
  for index,(h,a,goals) in enumerate([(0,1,(1,0)),(2,3,(0,0)),(0,2,(2,1)),(1,3,(1,1))]):
   row=['seed-'+str(index),date(2026,1,index+1),2026,h,a,*goals,'Test League','test-league','league',1,1,False,False,'F',0,None,'','seed','seed',None,None]
   c.execute('INSERT INTO matches VALUES('+','.join('?' for _ in row)+')',row)
  c.close();os.environ['PYTHONPATH']=os.pathsep.join([str(live.HERE/'engine'),*live.sys.path])
  live.run_club_model(cls.input,live.load_club_config(live.HERE/'engine/club_model.json'),output_database=cls.model)
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
 def setUp(self):
  self.state=self.root/self._testMethodName;self.responses.clear()
  self.responses.update({'/a':dict(schema=1,events=[]),'/b':dict(schema=1,events=[])})
  cfg=dict(sources=[dict(id=x,adapter='canonical_json',url=self.base+'/'+x) for x in ('a','b')],limitations=['Synthetic integration fixture.'])
  live.initialize(self.state,self.input,self.model,cfg)
 def event(self,eid='one',**kw):
  e=dict(id=eid,lifecycle='result',date='2026-01-10',season=2026,home=0,away=1,home_goals=2,away_goals=0,competition='Test League',competition_key='test-league',kind='league',home_tier=1,away_tier=1,neutral=False,cross_border=False,status='F',leg=0,tie_key=None,round_name='',aggregate_before_home=None,aggregate_after_home=None)
  e.update(kw);return e
 def run_update(self,**kw):return live.update(self.state,date(2026,1,31),**kw)
 def current(self):return live.read_json(self.state/'current.json')
 def test_new_no_change_and_late_correction(self):
  self.responses['/a']['events']=[self.event()];r=self.run_update();self.assertTrue(r['model_ran']);self.assertEqual(r['matches'],5)
  old=self.current();sha=live.file_sha(self.state/old['model']);r=self.run_update();self.assertEqual(r['result'],'no_change');self.assertEqual(self.current(),old);self.assertEqual(r['unchanged_responses'],2)
  self.responses['/a']['events'][0]['home_goals']=0;r=self.run_update();self.assertTrue(r['model_ran']);self.assertEqual(r['matches'],5);self.assertNotEqual(live.file_sha(self.state/self.current()['model']),sha)
 def test_fixture_final_and_retraction(self):
  e=self.event(lifecycle='fixture',home_goals=None,away_goals=None,status=None);self.responses['/a']['events']=[e]
  r=self.run_update();self.assertFalse(r['model_ran']);self.assertEqual(r['matches'],4);self.assertEqual(r['fixtures'],1)
  self.responses['/a']['events']=[self.event()];r=self.run_update();self.assertEqual(r['matches'],5);self.assertEqual(r['fixtures'],0)
  self.responses['/a']['events']=[e];r=self.run_update();self.assertEqual(r['matches'],4)
 def test_export_code_change_rebuilds_site_without_replaying_model(self):
  self.run_update();old=self.current();model_sha=live.file_sha(self.state/old['model'])
  with patch.object(live,'site_code_sha',return_value='new-publication-code'),patch.object(live,'build_site',wraps=live.build_site) as build:
   r=self.run_update();self.assertEqual(r['result'],'site_updated');self.assertFalse(r['model_ran'])
   self.assertIsNone(build.call_args.args[-1])
   self.assertEqual(live.file_sha(self.state/self.current()['model']),model_sha)
   self.assertEqual(self.run_update()['result'],'no_change')
 def test_source_outage_does_not_block_other(self):
  self.responses['/a']['events']=[self.event()];self.run_update();self.responses['/a']=503
  self.responses['/b']['events']=[self.event('two',date='2026-01-11',home=2,away=3)];r=self.run_update();self.assertEqual(r['matches'],6);self.assertEqual(r['sources'][0]['status'],'stale');self.assertEqual(r['sources'][1]['status'],'healthy')
 def test_exception_does_not_block_good_record(self):
  self.responses['/a']['events']=[self.event('bad',neutral=None),self.event('good',home=2,away=3)];r=self.run_update();self.assertEqual(r['matches'],5);self.assertEqual(r['exceptions'],1)
  self.assertEqual(live.read_json(self.state/self.current()['site']/'exceptions.json')[0]['reason'],'unknown_neutral_venue')
 def test_failed_publication_retains_old_and_retries(self):
  self.run_update();old=self.current();self.responses['/a']['events']=[self.event()]
  with self.assertRaisesRegex(RuntimeError,'Injected interruption'):self.run_update(fail_before_publish=True)
  self.assertEqual(self.current(),old);r=self.run_update();self.assertEqual(r['matches'],5)
 def test_duplicate_ids_retain_last_good_source(self):
  self.responses['/a']['events']=[self.event()];self.run_update();self.responses['/a']['events']=[self.event(),self.event()]
  r=self.run_update();self.assertFalse(r['model_ran']);self.assertEqual(r['matches'],5);self.assertEqual(r['sources'][0]['status'],'stale')
 def test_shootout_total_and_unknown_club_held(self):
  self.responses['/a']['events']=[self.event('pen',status='P',home_goals=5,away_goals=4),self.event('unknown',home=999),self.event('ok',home=2,away=3)]
  r=self.run_update();self.assertEqual(r['matches'],5);self.assertEqual(r['exceptions'],2)
 def test_concurrent_run_rejected(self):
  with live.locked(self.state):
   with self.assertRaisesRegex(RuntimeError,'already running'):self.run_update()

 def test_parallel_prefetch_reuses_response(self):
  c=live.state_db(self.state);f=live.Fetcher(self.state,c)
  try:
   f.prefetch([self.base+'/a',self.base+'/b']);n=f.requests
   self.assertEqual(f.get(self.base+'/a')['schema'],1);self.assertEqual(f.requests,n)
  finally:c.close()
 def test_ambiguous_physical_date_is_held(self):
  from identity_refresh import local_day
  with self.assertRaisesRegex(ValueError,'ambiguous_physical_local_date'):
   local_day('2026-07-06T02:30:00Z','Brazil',{'Brazil':['America/Sao_Paulo','America/Noronha']})
  self.assertEqual(str(local_day('2026-07-06T18:30:00Z','Brazil',{'Brazil':['America/Sao_Paulo','America/Noronha']})),'2026-07-06')

if __name__=='__main__':unittest.main(verbosity=2)
