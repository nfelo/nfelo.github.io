import unittest
from pathlib import Path
from compare_league_calibration import MeasuredModel,ENGINE,choose
from club_model import ClubRatingModel,load_club_config
import test_model_structure as model_support

class ComparisonTests(unittest.TestCase):
    def test_measurement_does_not_change_replay(self):
        support=model_support.ModelStructureTests()
        c=support.connection()
        self.addCleanup(c.close)
        support.add_match(c,'2018-01-01','league',1,1)
        support.add_match(c,'2018-02-01','continental',1,1)
        support.add_match(c,'2023-01-01','continental',1,1)
        c.execute("UPDATE matches SET away=2,cross_border=true WHERE kind='continental'")
        cfg=load_club_config(ENGINE/'club_model.json')
        baseline=ClubRatingModel(c,cfg,write_tables=False,evaluation_start='2018-01-01',evaluation_end='2026-10-26')
        measured=MeasuredModel(c,cfg,write_tables=False,evaluation_start='2018-01-01',evaluation_end='2026-10-26')
        self.assertEqual(baseline.replay(),measured.replay())
        self.assertEqual([baseline.mean(i) for i in range(3)],[measured.mean(i) for i in range(3)])
        self.assertEqual(measured.extra['selection']['all'][0],2)
        self.assertEqual(measured.extra['selection']['english_foreign'][0],1)
        self.assertEqual(measured.extra['review']['english_foreign'][0],1)

    def test_later_period_cannot_select_runner_up(self):
        def result(selection,review):
            return {'periods':{'selection':{'all':{'log_loss':1.},'international':{'log_loss':selection}},'review':{'all':{'log_loss':1.},'international':{'log_loss':review}}}}
        candidates={'baseline':result(.95,.95),'winner':result(.93,.97),'runner_up':result(.94,.92)}
        self.assertEqual(choose(candidates)['selected'],'baseline')
        candidates['winner']['periods']['review']['international']['log_loss']=.94
        self.assertEqual(choose(candidates)['selected'],'winner')

if __name__=='__main__':unittest.main()
