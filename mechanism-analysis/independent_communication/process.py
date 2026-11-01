"""Full-sample local ranking/action trace and decision-time message coverage."""
import json,re
from pathlib import Path
import numpy as np,pandas as pd
from scipy.stats import binomtest,t
from statsmodels.stats.multitest import multipletests
P=Path(__file__).resolve().parent;DATA=P.parents[1]/'data'
b=pd.read_csv(P/'branches.csv');v=pd.read_csv(P/'profit_outputs.csv');runs=pd.read_csv(P/'runs.csv');rows=[];messages=[]
number=re.compile(r'(?<![\w.])[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?')
zero=re.compile(r'(?:rho|ρ)\s*(?:is|to|=|:|of|at)?\s*(?:0(?:\.0+)?\b|zero)',re.I)
for _,r in b.iterrows():
 x=json.loads((DATA/r.record_path).read_text())['result'];role=f'Branch {r.branch} Specialist'
 cutoff=next(t['completed_at_s'] for t in x['turns'] if t['role']==role and t['tool_call']['name']=='submit_branch')
 z=v[(v.family==r.family)&(v.org==r.org)&(v.branch==r.branch)].drop_duplicates('label',keep='last')
 best=z.loc[z.value.idxmax(),'label'] if len(z)==2 else ''
 received=[]
 for m in x['protocol_deliveries']:
  if m['recipient']!=role or m['kind']!='message':continue
  before=m['read_at_s'] is not None and m['read_at_s']<cutoff
  text=m['content'];vals=[float(a.group().replace(',','').replace('−','-')) for a in number.finditer(text)]
  truths=[a['profit_m'] for a in x['economic_family']['local'][r.branch-1].values()]
  hit=sum(any(abs(n-truth)<.001 for n in vals) for truth in truths)
  messages.append(dict(family=r.family,org=r.org,recipient_branch=r.branch,delivery=m['delivery_id'],before_own_submission=before,own_correct_profit_values=hit,explicit_rho_zero=bool(zero.search(text)),text=text))
  if before:received.append((hit,bool(zero.search(text))))
 ownsent=[t['tool_call']['arguments'].get('text','') for t in x['turns'] if t['role']==role and t['tool_call']['name']=='send_message' and t['completed_at_s']<cutoff]
 rows.append(dict(family=r.family,org=r.org,branch=r.branch,final=r.final,optimal=r.optimal,wrong=r.wrong_final,computed_best=best,complete_local_comparison=len(z)==2,
      ranking_action_break=r.wrong_final and best==r.optimal,wrong_computed_ranking=r.wrong_final and best not in ['',r.optimal],
      received_own_correct_profit_pair=any(h==2 for h,_ in received),received_rho_zero=any(z for _,z in received),own_sent_rho_zero=any(zero.search(s) for s in ownsent),pre_filing_messages_sent=len(ownsent)))
a=pd.DataFrame(rows);a.to_csv(P/'branch_process.csv',index=False);pd.DataFrame(messages).to_csv(P/'message_process.csv',index=False)
r=runs.merge(a.groupby(['family','org'])[['ranking_action_break','wrong_computed_ranking']].any().reset_index(),on=['family','org']);r.to_csv(P/'runs_process.csv',index=False)
metrics=['detected_profit_output_error','wrong_after_correct_values','other_final_failure','ranking_action_break'];tests=[]
for m in metrics:
 w=r.pivot(index='family',columns='org',values=m);sa=int((w.independent&~w.mutual).sum());ma=int((~w.independent&w.mutual).sum())
 tests.append(dict(metric=m,independent=int(w.independent.sum()),mutual=int(w.mutual.sum()),independent_only=sa,mutual_only=ma,p_value=binomtest(sa,sa+ma).pvalue if sa+ma else 1))
tests=pd.DataFrame(tests);tests['p_holm_four']=multipletests(tests.p_value,method='holm')[1];tests.to_csv(P/'process_tests_four.csv',index=False)
loss=[]
for org,g in r.groupby('org'):
 loss.append(dict(org=org,total_loss=g.score_loss.mean(),ranking_action_break_loss=(g.score_loss*g.ranking_action_break).mean(),other_loss=(g.score_loss*~g.ranking_action_break).mean()))
pd.DataFrame(loss).to_csv(P/'ranking_loss_decomposition.csv',index=False)
print(tests.to_string(index=False));print(a.groupby('org')[['complete_local_comparison','ranking_action_break','wrong_computed_ranking','received_own_correct_profit_pair','received_rho_zero','own_sent_rho_zero']].sum().to_string());print(pd.DataFrame(loss).to_string(index=False))
assert len(a)==408 and len(r)==204
assert (r.wrong_final == (r.ranking_action_break|r.wrong_computed_ranking)).all()
