"""Regressions for rating changes unsupported by football results."""
import copy
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import duckdb
from club_model import ClubRatingModel, load_club_config


class ModelStructureTests(unittest.TestCase):
    def connection(self):
        c = duckdb.connect()
        self.addCleanup(c.close)
        c.execute('CREATE TABLE clubs(club INTEGER,code VARCHAR,name VARCHAR,country VARCHAR,country_name VARCHAR,country_code VARCHAR,continent VARCHAR,resolution VARCHAR)')
        c.executemany('INSERT INTO clubs VALUES (?,?,?,?,?,?,?,?)', [
            (0,'a','A','england','England','EN','Europe','same_entity'),
            (1,'b','B','england','England','EN','Europe','same_entity'),
            (2,'c','C','brazil','Brazil','BR','South America','same_entity'),
        ])
        c.execute('''CREATE TABLE matches(
            match_id VARCHAR,day DATE,season INTEGER,home INTEGER,away INTEGER,
            home_goals INTEGER,away_goals INTEGER,competition VARCHAR,
            competition_key VARCHAR,kind VARCHAR,home_tier INTEGER,away_tier INTEGER,
            neutral BOOLEAN,cross_border BOOLEAN,status VARCHAR,leg INTEGER,
            tie_key VARCHAR,round_name VARCHAR,source VARCHAR,source_ref VARCHAR,
            aggregate_before_home INTEGER,aggregate_after_home INTEGER)''')
        return c

    def model(self, c):
        cfg=load_club_config(Path(__file__).parent/'engine/club_model.json')
        return ClubRatingModel(c,cfg,write_tables=False)

    def add_match(self,c,day,kind,home_tier,away_tier):
        c.execute('INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [day,day,2026,0,1,2,0,'Example','example',kind,home_tier,away_tier,
             False,False,'F',0,None,'','test',day,None,None])

    def test_promotion_and_relegation_preserve_estimated_strength(self):
        m=self.model(self.connection())
        m._project_club(0,2026,3)
        m.club_rating[0]=210
        m.tier_rating[('england',2)]=-50
        m.tier_rating[('england',3)]=-90
        before=m.mean(0)
        for tier in (2,1,4,3):
            m._project_club(0,2026,tier)
            self.assertAlmostEqual(m.mean(0),before,places=12)

    def test_cup_default_tier_does_not_change_predictions_or_state(self):
        states=[]
        for cup_tier in (1,2):
            c=self.connection()
            self.add_match(c,'2026-02-01','league',2,2)
            self.add_match(c,'2026-02-08','domestic_cup',cup_tier,cup_tier)
            self.add_match(c,'2026-02-15','league',2,2)
            m=self.model(c);m.replay()
            states.append(m.checkpoint_state('2026-02-15',3,None))
        self.assertEqual(states[0],states[1])

    def test_league_transition_has_no_instant_forecast_bonus(self):
        states=[]
        for second_tier in (1,2):
            c=self.connection()
            self.add_match(c,'2026-02-01','league',2,2)
            self.add_match(c,'2026-02-08','league',second_tier,second_tier)
            m=self.model(c);m.replay()
            states.append((m.metrics,m.mean(0)-m.mean(1)))
        self.assertEqual(states[0],states[1])

    def test_cup_membership_inference_preserves_persisted_source_fields(self):
        from v10_live import FIELDS
        c=self.connection()
        self.add_match(c,'2026-02-01','league',2,2)
        self.add_match(c,'2026-02-08','domestic_cup',1,1)
        cfg=load_club_config(Path(__file__).parent/'engine/club_model.json')
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        output=duckdb.connect(str(Path(folder.name)/'model.duckdb'))
        self.addCleanup(output.close)
        model=ClubRatingModel(c,cfg,write_tables=True,output_connection=output)
        model.replay()
        columns=','.join(FIELDS)
        source=c.execute('SELECT '+columns+' FROM matches ORDER BY match_id').fetchall()
        rated=output.execute('SELECT '+columns+' FROM rated_matches ORDER BY match_id').fetchall()
        self.assertEqual(source,rated)
        self.assertEqual(model.last_tier[:2],[2,2])

    def test_continental_guest_is_real_regional_bridge(self):
        m=self.model(self.connection())
        for kind in ('continental','intercontinental','global','super_cup'):
            self.assertEqual(m.hierarchy_level(0,2,1,1,True,kind),'confederation')
            self.assertEqual(m.hierarchy_level(2,0,1,1,True,kind),'confederation')
        self.assertEqual(m.hierarchy_level(0,2,1,1,False,'league'),'club')
        self.assertEqual(m.hierarchy_level(0,2,1,1,True,'domestic_cup'),'club')

    def test_country_centring_cannot_change_any_club_strength(self):
        m=self.model(self.connection())
        day=date(2026,2,1).toordinal()
        m.country_rating=[80.,-30.]
        m.country_bridge_effective=[10.,4.]
        m.country_bridge_info_day=[day,day]
        m.confederation_rating=[25.,-25.]
        before=[m.mean(i) for i in range(3)]
        m._centre_country_components(day)
        self.assertEqual([m.mean(i) for i in range(3)],before)

    def test_conflicting_same_day_league_membership_is_rejected(self):
        c=self.connection()
        self.add_match(c,'2026-02-01','league',2,2)
        self.add_match(c,'2026-02-01','league',1,1)
        with self.assertRaisesRegex(ValueError,'conflicting league tiers'):
            self.model(c).replay()

    def test_reviewed_repair_is_idempotent_and_protects_newer_corrections(self):
        from ledger_repairs import apply_repairs
        c=self.connection();self.add_match(c,'2026-02-01','league',1,1)
        result=c.execute('SELECT * FROM matches')
        before={k[0]:str(v) if isinstance(v,date) else v for k,v in zip(result.description,result.fetchone())}
        after=dict(before,competition='Correct competition')
        payload={'matches':[{'before':before,'after':after,'reason':'Verified competition'}]}
        self.assertEqual(apply_repairs(c,payload)['applied'],1)
        self.assertEqual(apply_repairs(c,payload)['applied'],0)
        c.execute("UPDATE matches SET home_goals=3,competition='New source correction'")
        self.assertEqual(apply_repairs(c,payload)['changed_since_review'],['2026-02-01'])
        self.assertEqual(c.execute('SELECT home_goals,competition FROM matches').fetchone(),(3,'New source correction'))


if __name__=='__main__':
    unittest.main()
