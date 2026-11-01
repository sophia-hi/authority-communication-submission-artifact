"""Full-sample observable process indicators; no inference from absent traces."""
import json
from pathlib import Path
import pandas as pd
from scipy.stats import binomtest
from statsmodels.stats.multitest import multipletests
P=Path(__file__).resolve().parent
r=pd.read_csv(P/'runs.csv');t=pd.read_csv(P/'turns.csv');m=pd.read_csv(P/'messages.csv');a=pd.read_csv(P/'decisionmaker_comparisons.csv').fillna('');e=pd.read_csv(P/'comparison_expressions.csv').fillna('')
# Match message bodies to actual send turns, not delivery timestamps.
mt=[]
for _,z in m.iterrows():
 candidates=t[(t.family==z.family)&(t.rho==z.rho)&(t.org==z.org)&(t.role==z.sender)&(t.action=='send_message')]
 hits=[v for _,v in candidates.iterrows() if z.content.endswith(json.loads(v.arguments)['text'])]
 assert len(hits)==1,(z.family,z.org,z.delivery,len(hits))
 v=hits[0];d=z.to_dict();d.update(sent_at_s=v.time,sent_round=v['round'],before_sender_submission=bool(pd.notna(z.sender_submit_at) and v.time<z.sender_submit_at));mt.append(d)
pd.DataFrame(mt).to_csv(P/'message_timing.csv',index=False)
rows=[]
# Concurrent submissions have no first filer. Keep order-dependent indicators
# missing for those runs, rather than treating them as negative observations.
first_fields=('first_branch','first_filing_round','second_filing_round','first_filing_at','first_filing_excludes_optimum','other_correct_comparison_before_first_filing','other_correct_comparison_same_round_as_first_filing','other_correct_comparison_after_first_filing')
for _,z in r[r.rho==1].iterrows():
 sub=t[(t.family==z.family)&(t.rho==1)&(t.org==z.org)&t.action.isin(['submit_branch','submit_company'])].sort_values('round')
 aa=a[(a.family==z.family)&(a.org==z.org)];d=z.to_dict()
 d.update(n_decisionmakers=len(aa),n_all_four=int(aa.all_four.sum()),n_correct_full_ranking=int(aa.ranking_correct.sum()),n_correct_aligned_ranking=int(aa.aligned_ranking_correct.sum()))
 d['correct_full_rank_but_own_action_wrong']=any(v.ranking_correct and ((z.final!=z.optimal) if z.org!='mutual' else z.final[int(v.role[7])-1]!=z.optimal[int(v.role[7])-1]) for _,v in aa.iterrows())
 d.update(dict.fromkeys(first_fields))
 if z.org=='mutual':
  assert len(sub)==2 and sub.role.nunique()==2,(z.family,z.org)
  same_round=sub['round'].nunique()==1
  assert same_round==z.same_round_filing,(z.family,z.org)
  if not same_round:
   first,second=sub.iloc[0],sub.iloc[1];args=json.loads(first.arguments);branch=int(first.role[7])-1
   d.update(first_branch=branch+1,first_filing_round=int(first['round']),second_filing_round=int(second['round']),first_filing_at=first.time,first_filing_excludes_optimum=args['action']!=z.optimal[branch])
   latest={};rounds=[]
   for _,v in e[(e.family==z.family)&(e.org==z.org)&(e.role==second.role)&e.pair.ne('')].sort_values(['round','call','item']).iterrows():
    latest[v.pair]=v.value
    if len(latest)==4 and max(latest,key=latest.get)==z.optimal:rounds.append(v['round'])
   d['other_correct_comparison_before_first_filing']=any(q<first['round'] for q in rounds)
   d['other_correct_comparison_same_round_as_first_filing']=any(q==first['round'] for q in rounds)
   d['other_correct_comparison_after_first_filing']=any(q>first['round'] for q in rounds)
  best=aa[aa.all_four].computed_best.tolist();d['both_full_rankings_disagree']=len(best)==2 and best[0]!=best[1]
  d['both_full_rankings_agree_wrong']=len(best)==2 and best[0]==best[1] and best[0]!=z.optimal
 rows.append(d)
f=pd.DataFrame(rows);f.to_csv(P/'process_indicators.csv',index=False);f[~f.exact].to_csv(P/'all_failure_census.csv',index=False)
u=f[f.org=='mutual'];failures=u[~u.exact];different=failures[failures.same_round_filing.eq(False)]
summary=pd.DataFrame([dict(org='mutual',rho=1,runs=len(u),failures=len(failures),different_round_runs=int(u.same_round_filing.eq(False).sum()),same_round_runs=int(u.same_round_filing.eq(True).sum()),different_round_failures=len(different),same_round_failures=int(failures.same_round_filing.eq(True).sum()),earlier_submission_excludes_optimum_failures=int(different.first_filing_excludes_optimum.eq(True).sum()))])
summary.to_csv(P/'submission_timing_summary.csv',index=False)
print(summary.to_string(index=False))
# Paired exploratory tests of all three mutually exclusive error types.
z=r[r.rho==1].pivot(index='family',columns='org',values='category');tests=[]
for cat in ['neither_yields','both_yield','wrong_branch_yields']:
 mm=z.mutual.eq(cat);cc=z.centralized_two_way.eq(cat);b=int((mm&~cc).sum());c=int((cc&~mm).sum())
 tests.append(dict(category=cat,mutual=int(mm.sum()),centralized=int(cc.sum()),mutual_only=b,centralized_only=c,p=binomtest(b,b+c).pvalue if b+c else 1))
q=pd.DataFrame(tests);q['p_holm_3']=multipletests(q.p,method='holm')[1];q.to_csv(P/'error_category_tests.csv',index=False)
print(q.to_string(index=False))
for org,g in f.groupby('org'):
 print(org,'runs',len(g),'any full',sum(g.n_all_four>0),'any correct full',sum(g.n_correct_full_ranking>0),'correct full but own action wrong',sum(g.correct_full_rank_but_own_action_wrong))
 print('correct full but final wrong families',g[(g.n_correct_full_ranking>0)&~g.exact].family.tolist())
print(u[['first_filing_excludes_optimum','other_correct_comparison_before_first_filing','other_correct_comparison_same_round_as_first_filing','other_correct_comparison_after_first_filing','both_full_rankings_disagree','both_full_rankings_agree_wrong']].sum().to_string())
print('first excludes, other knows before',u[u.first_filing_excludes_optimum.eq(True)&u.other_correct_comparison_before_first_filing.eq(True)].family.tolist())
print('first excludes, other comparison in same round',u[u.first_filing_excludes_optimum.eq(True)&u.other_correct_comparison_same_round_as_first_filing.eq(True)].family.tolist())
print('first excludes, other knows after',u[u.first_filing_excludes_optimum.eq(True)&u.other_correct_comparison_after_first_filing.eq(True)].family.tolist())
print('correctrankactionwrong',u[u.correct_full_rank_but_own_action_wrong].family.tolist())
print('bothrankdisagree',u[u.both_full_rankings_disagree.eq(True)].family.tolist())
