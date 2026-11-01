"""Census of 102 paired rho=0 runs. Observable process indicators, not causal mediation.

All numeric matches and profit candidates retain source pointers. Missing calculations
are not errors. Policy labels cannot be inferred from an incorrect final action.
"""
import ast
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import binomtest, t
from statsmodels.stats.multitest import multipletests

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[2] / 'data'
TOL = .001  # millions; sensitivity also reported at .0001 and .01
# Reviewed false candidate: company sums ending with a local fixed cost.
EXCLUDE = {(88, 'single', 3, 6), (88, 'single', 3, 7)}
# Text-only inversion is evidenced AFTER the actor filed, not evidence of message causation.
LABEL_INVERSION = {(81, 'mutual', 1): 'delivery 5; A/B profits reversed; after own filing'}


def paired_test(frame, metric):
    w=frame.pivot(index='family',columns='org',values=metric).astype(int)
    delta=w.mutual-w.single; m=int(((w.mutual==1)&(w.single==0)).sum()); s=int(((w.single==1)&(w.mutual==0)).sum())
    return dict(metric=metric,n=len(w),single=int(w.single.sum()),mutual=int(w.mutual.sum()),
                difference_pp=100*delta.mean(),mutual_only=m,single_only=s,
                p_exact=binomtest(m,m+s).pvalue if m+s else 1.)


def main():
    index=json.loads((DATA/'combined_exploratory_3570_index.json').read_text())['rows']
    rows=[r for r in index if r['rho']==0 and r['organization'] in ['single','mutual']]
    assert len(rows)==204
    branch_rows=[]; run_rows=[]; candidate_rows=[]; match_rows=[]; sensitivity=[]
    for r in rows:
        x=json.loads((DATA/r['record_path']).read_text())['result']; econ=x['economic_family']; f=x['family_id']; org=x['organization']
        targets=[(j,p,econ['label_maps'][j][p],v['profit_m'],v['fixed_cost_m']) for j,l in enumerate(econ['local']) for p,v in l.items()]
        filing={}
        for turn in x['turns']:
            if turn['tool_call']['name'] in ['submit_company','submit_branch'] and not turn['already_filed_before_turn']:
                filing.setdefault(turn['role'],turn['completed_at_s'])
        values=[]; candidates=[]
        for c in x['calculator_calls']:
            if c['completed_at_s']>filing.get(c['role'],float('-inf')):continue
            for i,v in enumerate(c['output'].get('results',[]),1):
                expression=v.get('expression',''); value=v.get('value')
                if not isinstance(value,(float,int)):continue
                values.append((c['role'],c['calculator_call_id'],i,value,expression))
                try:
                    node=ast.parse(expression,mode='eval').body
                    cost=node.right.value if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Sub) and isinstance(node.right,ast.Constant) else None
                except (SyntaxError,ValueError):cost=None
                matching=[q for q in targets if isinstance(cost,(int,float)) and abs(q[4]-cost)<1e-5]
                if len(matching)!=1 or (f,org,c['calculator_call_id'],i) in EXCLUDE:continue
                j,p,label,truth,fc=matching[0]
                if org=='mutual' and c['role']!=f'Branch {j+1} Specialist':continue
                candidates.append(dict(family=f,org=org,branch=j+1,policy=p,label=label,call=c['calculator_call_id'],item=i,
                    expression=expression,value=value,true_profit=truth,error=abs(value-truth)>TOL,absolute_error=abs(value-truth),record_path=r['record_path']))
        candidate_rows+=candidates
        br=[]
        for j in range(2):
            role='Owner' if org=='single' else f'Branch {j+1} Specialist'
            target=[q for q in targets if q[0]==j]; hit=[]
            for _,p,a,truth,_ in target:
                matches=[v for v in values if v[0]==role and abs(v[3]-truth)<TOL]
                hit.append(bool(matches))
                for ro,cid,i,val,exp in matches:
                    match_rows.append(dict(family=f,org=org,branch=j+1,label=a,policy=p,call=cid,item=i,value=val,true_profit=truth,expression=exp))
            wrong=x['submitted_plan'][j]!=x['optimal_plan'][j]
            inversion=LABEL_INVERSION.get((f,org,j+1),'')
            own=[c for c in candidates if c['branch']==j+1]
            br.append(dict(family=f,org=org,branch=j+1,wrong_final=wrong,both_correct_profit_values=all(hit),
                wrong_after_correct_values=wrong and all(hit),detected_profit_output_error=any(c['error'] for c in own),
                profit_output_evaluable=bool(own),candidate_count=len(own),label_status='confirmed_post_filing_inversion' if inversion else
                ('unobservable_no_text' if org=='single' else 'no_confirmed_inversion_in_reviewed_messages'),label_evidence=inversion,
                final=x['submitted_plan'][j],optimal=x['optimal_plan'][j],record_path=r['record_path']))
        branch_rows+=br
        post=any(b['wrong_after_correct_values'] for b in br); wrong=not x['exact_optimum']; anyerr=any(c['error'] for c in candidates)
        run_rows.append(dict(family=f,org=org,run_id=r['run_id'],record_path=r['record_path'],score=x['decision_score'],
            wrong_final=wrong,wrong_after_correct_values=post,other_final_failure=wrong and not post,
            detected_profit_output_error=anyerr,all_four_correct_values=all(b['both_correct_profit_values'] for b in br),
            no_identifiable_profit_output=not candidates,wrong_branches=sum(b['wrong_final'] for b in br),
            stage='correct_final' if not wrong else 'wrong_after_correct_values' if post else 'wrong_without_correct_pair',
            label_status='unobservable_no_text' if org=='single' else 'confirmed_post_filing_inversion' if any(b['label_evidence'] for b in br) else 'no_confirmed_inversion',
            score_loss=100-x['decision_score'],postcalc_score_loss=(100-x['decision_score'])*post,
            other_score_loss=(100-x['decision_score'])*(wrong and not post)))
        for tol in [.0001,.001,.01]:
            correct=[]
            for j in range(2):
                role='Owner' if org=='single' else f'Branch {j+1} Specialist'
                both=all(any(ro==role and abs(val-truth)<tol for ro,_,_,val,_ in values) for jj,_,_,truth,_ in targets if jj==j)
                correct.append(both and x['submitted_plan'][j]!=x['optimal_plan'][j])
            sensitivity.append(dict(family=f,org=org,tolerance_m=tol,wrong_after_correct_values=any(correct),detected_profit_output_error=any(c['absolute_error']>tol for c in candidates)))
    runs=pd.DataFrame(run_rows).sort_values(['family','org']); branches=pd.DataFrame(branch_rows).sort_values(['family','org','branch'])
    assert runs.groupby('org').size().eq(102).all() and len(branches)==408
    assert (runs.wrong_final==(runs.wrong_after_correct_values | runs.other_final_failure)).all()
    assert not (runs.wrong_after_correct_values & runs.other_final_failure).any()
    # Every numeric hit is also tied to the same policy by an identifiable fixed cost.
    keys=['family','org','branch','label','call','item']
    verified=pd.DataFrame(match_rows).merge(pd.DataFrame(candidate_rows)[keys],on=keys,how='left',indicator=True)
    assert verified['_merge'].eq('both').all()
    reviewed=pd.read_csv(HERE/'manual_review.csv')
    assert set(map(tuple,reviewed[['family','org']].to_numpy())) == set(map(tuple,runs.loc[runs.detected_profit_output_error,['family','org']].to_numpy()))
    for name,frame in [('runs',runs),('branches',branches),('profit_outputs',pd.DataFrame(candidate_rows)),('correct_value_matches',pd.DataFrame(match_rows)),('sensitivity',pd.DataFrame(sensitivity))]:frame.to_csv(HERE/f'{name}.csv',index=False)
    metrics=['detected_profit_output_error','wrong_after_correct_values','other_final_failure']
    tests=pd.DataFrame([paired_test(runs,m) for m in metrics]); tests['p_holm_three']=multipletests(tests.p_exact,method='holm')[1]
    tests.to_csv(HERE/'mechanism_tests.csv',index=False)
    paired=pd.DataFrame([paired_test(runs,m) for m in ['wrong_final','all_four_correct_values']]);paired.to_csv(HERE/'supplemental_tests.csv',index=False)
    burdens=[]
    for metric in ['score_loss','postcalc_score_loss','other_score_loss']:
        w=runs.pivot(index='family',columns='org',values=metric); delta=w.single-w.mutual; se=delta.std(ddof=1)/np.sqrt(len(delta))
        burdens.append(dict(metric=metric,single=w.single.mean(),mutual=w.mutual.mean(),single_minus_mutual=delta.mean(),paired_se=se,ci_low=delta.mean()-t.ppf(.975,101)*se,ci_high=delta.mean()+t.ppf(.975,101)*se))
    pd.DataFrame(burdens).to_csv(HERE/'score_loss_decomposition.csv',index=False)
    print(tests.to_string(index=False)); print(paired.to_string(index=False));print(runs.groupby('org')[['all_four_correct_values','no_identifiable_profit_output','wrong_branches']].sum());print(pd.DataFrame(burdens).to_string(index=False))
    print('Failures:');print(runs[runs.wrong_final][['family','org','stage','detected_profit_output_error']].to_string(index=False))

if __name__=='__main__':main()
