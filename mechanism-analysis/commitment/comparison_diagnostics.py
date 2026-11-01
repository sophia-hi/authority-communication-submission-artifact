"""Summarize conservatively reconstructed company comparisons at rho=1."""
from pathlib import Path
import pandas as pd
P=Path(__file__).resolve().parent;e=pd.read_csv(P/'comparison_expressions.csv').fillna('');r=pd.read_csv(P/'runs.csv');out=[]
for v in r[r.rho==1].itertuples():
 q=e[(e.family==v.family)&(e.org==v.org)&e.pair.ne('')].sort_values(['time','call','item']);latest=q.drop_duplicates('pair',keep='last').set_index('pair').value.to_dict();cond={k:z for k,z in latest.items() if k[v.reporting_branch-1]==v.report_action}
 out.append(dict(family=v.family,org=v.org,pairs=len(latest),report_actions_evaluated=len({k[v.reporting_branch-1] for k in latest}),conditional_comparison=len(cond)==2,computed_conditional_best=max(cond,key=cond.get) if len(cond)==2 else '',actual_conditional_best=v.conditional_best,final=v.final,optimal=v.optimal,exact=v.exact))
a=pd.DataFrame(out);a['conditional_ranking_correct']=a.computed_conditional_best.eq(a.actual_conditional_best);a.to_csv(P/'lead_comparison_audit.csv',index=False)
a=pd.read_csv(P/'decisionmaker_comparisons.csv').fillna('').merge(r[r.rho==1][['family','org','reporting_branch','lead_branch']],on=['family','org']);z=a[a.all_four].copy();z['report_component_mismatch']=[v.computed_best[v.reporting_branch-1]!=v.final[v.reporting_branch-1] for v in z.itertuples()];z['lead_component_matches']=[v.computed_best[v.lead_branch-1]==v.final[v.lead_branch-1] for v in z.itertuples()];z.to_csv(P/'full_comparison_implementation.csv',index=False)
paired=[]
for rho in sorted(r.rho.unique()):
 g=r[r.rho==rho];c=g[g.org=='committed_handoff'].set_index('family');i=g[g.org=='informational_handoff'].set_index('family');same=c.report_action.eq(i.report_action)
 assert c.reporting_branch.eq(i.reporting_branch).all() and c.optimal.eq(i.optimal).all()
 for f in c.index:paired.append(dict(family=f,rho=rho,same_reporting_action=bool(same[f]),committed_final=c.loc[f,'final'],informational_final=i.loc[f,'final'],optimal=c.loc[f,'optimal'],committed_exact=c.loc[f,'exact'],informational_exact=i.loc[f,'exact'],committed_best_response=c.loc[f,'lead_conditional_optimal'],informational_best_response=i.loc[f,'lead_conditional_optimal']))
pd.DataFrame(paired).to_csv(P/'matched_process.csv',index=False)
