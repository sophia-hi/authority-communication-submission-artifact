"""All matched handoff runs: outcomes, actual communication, and choice decomposition."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from scipy.stats import t,binomtest
P=Path(__file__).resolve().parent;ROOT=P.parents[1];DATA=ROOT/'data';rows=[];msgs=[]
idx=json.loads((DATA/'combined_exploratory_3570_index.json').read_text())['rows']
for r in idx:
 if r['organization'] not in ['committed_handoff','informational_handoff']:continue
 raw=json.loads((DATA/r['record_path']).read_text());x=raw['result'];e=x['economic_family'];org=r['organization'];f=r['family_id'];rho=r['rho'];rb=x['reporting_branch_index'];lb=x['lead_branch_index'];final=x['submitted_plan'];opt=x['optimal_plan'];local=e['labeled_local_plan']
 util={''.join(e['label_maps'][j][pol] for j,pol in enumerate(k.split('|'))):v for k,v in e['utilities'][str(float(rho))].items()}
 constrained={k:v for k,v in util.items() if k[rb]==final[rb]};best=max(constrained,key=constrained.get);maxv=max(util.values());cmax=constrained[best];actual=util[final]
 assert abs(maxv-actual-x['raw_regret_m'])<1e-8
 actions=[v for v in x['turns'] if v['tool_call']['name'] in ['send_message','send_report','commit_and_handoff','submit_branch','finish_communication','decline_message','wait_for_report']]
 sends=[v for v in actions if v['tool_call']['name'] in ['send_message','send_report','commit_and_handoff']];assert all(v['role']=='Reporting' for v in sends)
 leadsub=next(v for v in actions if v['role']=='Lead' and v['tool_call']['name']=='submit_branch');reportsub=next(v for v in actions if v['role']=='Reporting' and v['tool_call']['name'] in ['submit_branch','commit_and_handoff'])
 dm=[v for v in x['protocol_deliveries'] if v['kind'] in ['message','report','committed_handoff']];assert len(dm)==len(sends)
 read=[]
 for i,m in enumerate(dm):
  hits=[v for v in sends if m['content'].endswith(v['tool_call']['arguments']['text'])];assert len(hits)==1
  v=hits[0];before=m['read_at_s'] is not None and m['read_at_s']<leadsub['completed_at_s'];read.append(before)
  msgs.append(dict(family=f,rho=rho,org=org,delivery=m['delivery_id'],opening=i==0,sent_at=v['completed_at_s'],sent_round=v['round_number'],sent_after_reporting_filed=v['already_filed_before_turn'],read_at=m['read_at_s'],read_before_lead=before,lead_submit=leadsub['completed_at_s'],status=m['decision_delivery_status'],text=v['tool_call']['arguments']['text']))
 assert read[0]
 assert len(sends)==r['messages']
 assert reportsub['tool_call']['arguments']['action']==final[rb]
 assert leadsub['tool_call']['arguments']['action']==final[lb]
 first=sends[0];assert (org!='committed_handoff') or first['tool_call']['name']=='commit_and_handoff'
 rows.append(dict(family=f,rho=rho,org=org,score=x['decision_score'],exact=int(x['exact_optimum']),final=final,optimal=opt,local=local,reporting_branch=rb+1,lead_branch=lb+1,report_action=final[rb],lead_action=final[lb],report_local=final[rb]==local[rb],report_optimal=final[rb]==opt[rb],lead_conditional_optimal=final==best,conditional_best=best,report_restriction_regret=maxv-cmax,lead_response_regret=cmax-actual,total_regret=maxv-actual,messages=len(sends),extra_sent=len(sends)-1,extra_read=sum(read[1:]),extra_unread=len(read[1:])-sum(read[1:]),extra_after_report=sum(v['already_filed_before_turn'] for v in sends[1:]),lead_round=leadsub['round_number'],report_round=reportsub['round_number'],report_before_lead=reportsub['completed_at_s']<leadsub['completed_at_s'],same_round=reportsub['round_number']==leadsub['round_number'],report_time=reportsub['completed_at_s'],lead_time=leadsub['completed_at_s'],record_path=r['record_path']))

d=pd.DataFrame(rows).sort_values(['rho','family','org']);d.to_csv(P/'runs.csv',index=False);pd.DataFrame(msgs).to_csv(P/'messages.csv',index=False)
assert len(d)==1020 and d.groupby(['rho','family']).size().eq(2).all()
results=[];deltas=[]
for rho,g in d.groupby('rho'):
 w=g.pivot(index='family',columns='org',values=['score','exact']);a=w.score.committed_handoff-w.score.informational_handoff;b=w.exact.committed_handoff-w.exact.informational_handoff;se=a.std(ddof=1)/np.sqrt(102);plus=int((b==1).sum());minus=int((b==-1).sum())
 results.append(dict(rho=rho,informational_score=w.score.informational_handoff.mean(),committed_score=w.score.committed_handoff.mean(),score_diff=a.mean(),score_se=se,score_p=2*t.sf(abs(a.mean()/se),101),informational_exact=int(w.exact.informational_handoff.sum()),committed_exact=int(w.exact.committed_handoff.sum()),exact_diff_pp=b.mean()*100,committed_only=plus,informational_only=minus,exact_p=binomtest(plus,plus+minus).pvalue if plus+minus else 1))
 for f in w.index:deltas.append(dict(family=f,rho=rho,score=a.loc[f],exact=b.loc[f]))
o=pd.DataFrame(results);o.to_csv(P/'paired_outcomes.csv',index=False)
pd.DataFrame(deltas).to_csv(P/'paired_differences.csv',index=False)
s=d.groupby(['rho','org']).agg(n=('family','size'),messages=('messages','sum'),extra_sent=('extra_sent','sum'),runs_extra_sent=('extra_sent',lambda s:sum(s>0)),extra_read=('extra_read','sum'),runs_extra_read=('extra_read',lambda s:sum(s>0)),extra_unread=('extra_unread','sum'),extra_after_report=('extra_after_report','sum'),report_local=('report_local','sum'),report_optimal=('report_optimal','sum'),lead_conditional_optimal=('lead_conditional_optimal','sum'),report_regret=('report_restriction_regret','mean'),lead_regret=('lead_response_regret','mean'),score=('score','mean'),exact=('exact','sum'))
s.to_csv(P/'process_summary.csv');d[d.exact==0].to_csv(P/'all_failures.csv',index=False)
print(o.to_string(index=False));print(s.to_string())
