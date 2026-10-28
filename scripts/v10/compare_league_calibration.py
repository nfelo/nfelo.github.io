"""Fixed, chronological league-pooling comparison against the saved release."""
from pathlib import Path
from collections import defaultdict
import argparse,hashlib,json,math,sys,time

HERE=Path(__file__).resolve().parent
ENGINE=HERE/'engine'
sys.path.insert(0,str(ENGINE))
import duckdb
from club_model import ClubRatingModel,load_club_config,BOUNDARY_KINDS

class MeasuredModel(ClubRatingModel):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.extra=defaultdict(lambda:defaultdict(lambda:[0.0]*6))
        self.foreign_games=defaultdict(int)

    def _project_all_to_year(self,year):
        old=self.projected_year
        super()._project_all_to_year(year)
        if year!=old and year in (1950,2000,2018,2023,2026):
            print('Replay reached',year,flush=True)

    def hierarchy_level(self,home,away,home_tier,away_tier,cross_border,kind):
        international=bool(cross_border and kind in BOUNDARY_KINDS and self.clubs[home].country!=self.clubs[away].country)
        self.metric_match=(home,away,international,self.foreign_games[home],self.foreign_games[away])
        if international:
            self.foreign_games[home]+=1
            self.foreign_games[away]+=1
        return super().hierarchy_level(home,away,home_tier,away_tier,cross_border,kind)

    def _record_metric(self,bucket,probability,probabilities,score):
        super()._record_metric(bucket,probability,probabilities,score)
        if bucket!='all':return
        home,away,international,home_experience,away_experience=self.metric_match
        phase='selection' if self.projected_year<=2022 else 'review'
        home_country=self.clubs[home].country
        away_country=self.clubs[away].country
        groups=['all']
        if international:
            groups+=['international','english_foreign' if 'england' in (home_country,away_country) else 'non_english_foreign']
            if min(home_experience,away_experience)<10:groups.append('international_new_entrants')
        outcome=(1.,0.,0.) if score==1 else (0.,0.,1.) if score==0 else (0.,1.,0.)
        loss=-math.log(max(1e-15,probability))
        brier=sum((p-o)**2 for p,o in zip(probabilities,outcome))
        predicted=probabilities[0]+0.5*probabilities[1]
        for group in groups:
            values=self.extra[phase][group]
            observed=score
            forecast=predicted
            if group=='english_foreign' and home_country!='england':forecast,observed=1-predicted,1-score
            for i,x in enumerate((1,loss,loss*loss,brier,forecast,observed)):values[i]+=x

def choose(results):
    baseline=results['baseline']['periods']
    eligible=[name for name,value in results.items() if value['periods']['selection']['all']['log_loss']<=baseline['selection']['all']['log_loss']+0.001]
    candidate=min(eligible,key=lambda name:(results[name]['periods']['selection']['international']['log_loss'],name))
    improvement=baseline['selection']['international']['log_loss']-results[candidate]['periods']['selection']['international']['log_loss']
    if improvement<0.001:
        return {'selected':'baseline','selection_winner':candidate,'reason':'No eligible candidate improved selection-period international log loss by at least 0.001.','international_improvement':improvement}
    review=results[candidate]['periods']['review']
    if review['all']['log_loss']>baseline['review']['all']['log_loss']+0.005 or review['international']['log_loss']>baseline['review']['international']['log_loss']+0.01:
        return {'selected':'baseline','selection_winner':candidate,'reason':'Selected candidate failed the predeclared later-period regression guard; no runner-up selected.','international_improvement':improvement}
    return {'selected':candidate,'selection_winner':candidate,'reason':'Lowest eligible selection-period international log loss; later-period guard passed.','international_improvement':improvement}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--candidate')
    mode.add_argument('--select',action='store_true')
    args=parser.parse_args()
    protocol=json.loads(args.protocol.read_text())
    args.output.mkdir(parents=True,exist_ok=True)
    if args.select:
        results={name:json.loads((args.output/(name+'.json')).read_text()) for name in protocol['candidates']}
        expected_protocol=hashlib.sha256(args.protocol.read_bytes()).hexdigest()
        if {r['protocol_sha256'] for r in results.values()}!={expected_protocol}:
            raise ValueError('Candidate results use different comparison protocols')
        if {r['engine_sha256'] for r in results.values()}!={protocol['engine_sha256']}:
            raise ValueError('Candidate results use different engines')
        if {r['matches'] for r in results.values()}!={1690260}:
            raise ValueError('Candidate results do not use the recorded archive')
        for phase in ('selection','review'):
            for group in ('all','international','english_foreign'):
                if len({r['periods'][phase][group]['matches'] for r in results.values()})!=1:
                    raise ValueError('Candidate evaluation samples differ')
        print(json.dumps(choose(results),indent=2))
        return
    if args.input is None:parser.error('--input is required for a candidate replay')
    name=args.candidate
    if name not in protocol['candidates']:parser.error('candidate is not in the recorded protocol')
    engine_hash=hashlib.sha256((ENGINE/'club_model.py').read_bytes()).hexdigest()
    if engine_hash!=protocol['engine_sha256']:raise ValueError('Engine differs from the recorded comparison')
    change=protocol['candidates'][name]
    config=dict(protocol['baseline_parameters'])
    config.update(change)
    c=duckdb.connect(str(args.input),read_only=True)
    c.execute('SET threads=1')
    start=time.monotonic()
    m=MeasuredModel(c,config,write_tables=False,evaluation_start='2018-01-01',evaluation_end='2026-10-26')
    result=m.replay()
    measured={}
    for phase,groups in m.extra.items():
        measured[phase]={}
        for group,(n,loss,square,brier,predicted,observed) in groups.items():
            measured[phase][group]={'matches':int(n),'log_loss':loss/n,'brier':brier/n,'predicted_score':predicted/n,'actual_score':observed/n}
    anchor=m._publication_anchor()
    latest=max(m.last_match_day)
    rankings=sorted([{'code':club.code,'name':club.name,'country':club.country,'rating':m.mean(i,anchor),'club_component':m.club_rating[i],'league_component':sum(m.components(i,anchor)[1:])} for i,club in enumerate(m.clubs) if m.initialised[i] and m.last_match_day[i]>=latest-550],key=lambda x:(-x['rating'],x['code']))
    for i,club in enumerate(rankings,1):club['rank']=i
    output={'candidate':name,'changes':change,'engine_sha256':hashlib.sha256((ENGINE/'club_model.py').read_bytes()).hexdigest(),'protocol_sha256':hashlib.sha256(args.protocol.read_bytes()).hexdigest(),'matches':result['matches'],'all_period_metrics':result['metrics'],'periods':measured,'current_top_30':rankings[:30],'reported_clubs':[x for x in rankings if x['code'] in ('c16fdac6b4386','ca4b358b5cc51','c13a9c5ee7aa1','c0d90fadce1a1')],'seconds':round(time.monotonic()-start,1)}
    (args.output/(name+'.json')).write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'candidate':name,'periods':measured,'reported_clubs':output['reported_clubs'],'seconds':output['seconds']}),flush=True)

if __name__=='__main__':main()
