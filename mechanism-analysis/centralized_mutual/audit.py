"""All endpoint runs: local preferences, joint outcomes and filing-time information."""
import json
from pathlib import Path
import pandas as pd
P=Path(__file__).resolve().parent;ROOT=P.parents[1];DATA=ROOT/'data'
idx=json.loads((DATA/'combined_exploratory_3570_index.json').read_text())['rows'];rows=[];msgs=[];turnrows=[]
for r in idx:
 if r['rho'] not in [0,1] or r['organization'] not in ['mutual','centralized_two_way']:continue
 x=json.loads((DATA/r['record_path']).read_text())['result'];e=x['economic_family'];rho=r['rho'];f=r['family_id'];org=r['organization']
 local=e['labeled_local_plan'];opt=x['optimal_plan'];final=x['submitted_plan'];yielded=[j for j in [0,1] if final[j]!=local[j]];needed=[j for j in [0,1] if opt[j]!=local[j]]
 sub=[t for t in x['turns'] if t['tool_call']['name'] in ['submit_branch','submit_company'] and not t['already_filed_before_turn']];cut={t['role']:t['completed_at_s'] for t in sub}
 if org=='mutual':assert len(sub)==2
 else:assert len(sub)==1
 if rho==0:category='optimal' if x['exact_optimum'] else 'one_branch_error' if len(yielded)==1 else 'two_branch_error'
 else:
  assert len(needed)==1
  category='optimal' if final==opt else 'neither_yields' if len(yielded)==0 else 'both_yield' if len(yielded)==2 else 'wrong_branch_yields'
 for m in x['protocol_deliveries']:
  if m['kind'] not in ['message','report']:continue
  recipientcut=cut.get(m['recipient'])
  before=recipientcut is not None and m['read_at_s'] is not None and m['read_at_s']<recipientcut
  sendercut=cut.get(m['sender'])
  msgs.append(dict(family=f,rho=rho,org=org,delivery=m['delivery_id'],sender=m['sender'],recipient=m['recipient'],read_at_s=m['read_at_s'],before_recipient_submission=before,recipient_submit_at=recipientcut,sender_submit_at=sendercut,status=m['decision_delivery_status'],content=m['content']))
 for t in x['turns']:
  name=t['tool_call']['name']
  if name in ['send_message','submit_branch','submit_company']:
   turnrows.append(dict(family=f,rho=rho,org=org,role=t['role'],turn=t['turn_number'],round=t['round_number'],time=t['completed_at_s'],action=name,arguments=json.dumps(t['tool_call']['arguments'])))
 rows.append(dict(family=f,rho=rho,org=org,score=x['decision_score'],exact=x['exact_optimum'],local_plan=local,optimal=opt,final=final,category=category,sacrifice_branch=needed[0]+1 if len(needed)==1 else None,reporting_branch=x['reporting_branch_index']+1,lead_branch=x['lead_branch_index']+1,needed_sacrifice_on_reporting=bool(needed and needed[0]==x['reporting_branch_index']),same_round_filing=(sub[0]['round_number']==sub[1]['round_number']) if org=='mutual' else None,filing_gap=abs(sub[0]['completed_at_s']-sub[1]['completed_at_s']) if org=='mutual' else 0,record_path=r['record_path']))

d=pd.DataFrame(rows).sort_values(['rho','family','org']);d.to_csv(P/'runs.csv',index=False);pd.DataFrame(msgs).to_csv(P/'messages.csv',index=False);pd.DataFrame(turnrows).to_csv(P/'turns.csv',index=False)
print(pd.crosstab([d.rho,d.org],d.category).to_string());print(d[d.rho==1].groupby(['org','needed_sacrifice_on_reporting']).exact.agg(['sum','count']).to_string());print(d[(d.rho==1)&(d.org=='mutual')].groupby('same_round_filing').exact.agg(['sum','count']).to_string())
assert len(d)==408 and d.groupby(['rho','family']).size().eq(2).all()
