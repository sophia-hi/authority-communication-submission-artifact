"""All 102 matched rho=1 tasks: information, company computation and final choice.

Recorded numeric coverage is evidence of explicit values, not proof of comprehension
or absence of equivalent information. Only decision-time evidence enters indicators.
"""
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import binomtest, fisher_exact
from statsmodels.stats.multitest import multipletests

HERE=Path(__file__).resolve().parent
DATA=HERE.parents[2]/'data'
NUMBER=re.compile(r'(?<![\w.])[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?')
# Reviewed requests explicitly ask for volumes AND unit margins, not generic inputs.
REQUESTS={4:[3],5:[3],6:[1],7:[1],11:[3],12:[1,3],20:[3],24:[1,3],27:[3],31:[3],
          34:[5],35:[3],36:[3],37:[3],38:[3],40:[3],41:[3],45:[3],54:[3],59:[3],60:[3],
          61:[3],62:[3],71:[3],75:[3],76:[3],78:[3],81:[5],82:[3],87:[3],91:[3],98:[3],102:[3]}


def numbers(s):
    return [(float(m.group().replace(',','').replace('−','-')),m.start(),m.end()) for m in NUMBER.finditer(s)]


def tolerance(kind,scale=1):return (1. if kind=='units' else .001)*scale


def paired_test(d,metric):
    w=d.pivot(index='family',columns='org',values=metric).astype(bool)
    a=w.single;b=w.centralized_two_way;sa=int((a&~b).sum());ca=int((b&~a).sum())
    return dict(metric=metric,single=int(a.sum()),central=int(b.sum()),single_only=sa,central_only=ca,
                difference_pp=100*(b.astype(int)-a.astype(int)).mean(),p_value=binomtest(sa,sa+ca).pvalue if sa+ca else 1.)


def main():
    index=json.loads((DATA/'combined_exploratory_3570_index.json').read_text())['rows']
    index=[r for r in index if r['rho']==1 and r['organization'] in ['single','centralized_two_way']]
    runs=[];evidence=[];requests=[];messages=[];reuse=[];sens=[];failure_context=[]
    for r in index:
        x=json.loads((DATA/r['record_path']).read_text())['result'];e=x['economic_family'];f=x['family_id'];org=x['organization']
        role='Owner' if org=='single' else 'Lead';report_branch=x['reporting_branch_index']
        filing=next(z for z in x['turns'] if z['role']==role and z['tool_call']['name']=='submit_company')
        cutoff=filing['completed_at_s']
        calc=[c for c in x['calculator_calls'] if c['role']==role and c['completed_at_s']<cutoff]
        targets={(j,e['label_maps'][j][p],k):v[k] for j,l in enumerate(e['local']) for p,v in l.items() for k in ['profit_m','units','unit_margin']}
        company={''.join(e['label_maps'][j][p] for j,p in enumerate(pair.split('|'))):value for pair,value in e['utilities']['1.0'].items()}
        company_matches=set();available=set();observed=[]
        for c in calc:
            for i,v in enumerate(c['output'].get('results',[]),1):
                value=v.get('value');expression=v.get('expression','')
                if not isinstance(value,(float,int)):continue
                observed.append(value)
                for key,truth in targets.items():
                    if abs(value-truth)<tolerance(key[2]):
                        available.add(key);evidence.append(dict(family=f,org=org,source='calculator',source_id=f'{c["calculator_call_id"]}.{i}',target=str(key),truth=truth,value=value,context=expression))
                for pair,truth in company.items():
                    if abs(value-truth)<.001:
                        company_matches.add(pair);evidence.append(dict(family=f,org=org,source='company_calculator',source_id=f'{c["calculator_call_id"]}.{i}',target=pair,truth=truth,value=value,context=expression))
        deliveries=x['protocol_deliveries'];report_matches={};report_times={};report_values=[]
        for m in deliveries:
            if m['sender']!='Reporting' or m['recipient']!='Lead':continue
            before=m['decision_delivery_status']=='delivered_before_decision' and m['read_at_s'] is not None and m['read_at_s']<cutoff
            hit=set();content=m['content']
            for key,truth in targets.items():
                if key[0]!=report_branch:continue
                for value,start,end in numbers(content):
                    if abs(value-truth)<tolerance(key[2]):
                        hit.add(key)
                        evidence.append(dict(family=f,org=org,source='read_report' if before else 'unread_or_late_report',source_id=m['delivery_id'],target=str(key),truth=truth,value=value,context=content[max(0,start-65):end+35]))
            messages.append(dict(family=f,delivery=m['delivery_id'],before_decision=before,read_at_s=m['read_at_s'],matched_values=len(hit),matched_targets=';'.join(map(str,sorted(hit))),content=content))
            if before:
                available|=hit;report_matches[m['delivery_id']]=hit;report_times[m['delivery_id']]=m['read_at_s'];report_values.extend(v for v,_,_ in numbers(content))
                for pair,truth in company.items():
                    for value,start,end in numbers(content):
                        if abs(value-truth)<.001:
                            company_matches.add(pair);evidence.append(dict(family=f,org=org,source='read_company_report',source_id=m['delivery_id'],target=pair,truth=truth,value=value,context=content[max(0,start-30):end+25]))
        report_all=set().union(*report_matches.values()) if report_matches else set()
        opening_id=next((m['delivery_id'] for m in deliveries if m['sender']=='Reporting' and m['recipient']=='Lead'),None)
        opening=report_matches.get(opening_id,set());new=report_all-opening
        reused=set()
        for mid,hit in report_matches.items():
            for c in calc:
                if c['started_at_s']<report_times[mid]:continue
                expression=' '.join(v.get('expression','') for v in c['output'].get('results',[]))
                for key in sorted(hit):
                    if key[2]=='profit_m':continue
                    if any(abs(v-targets[key])<tolerance(key[2]) for v,_,_ in numbers(expression)):
                        reused.add(key);reuse.append(dict(family=f,delivery=mid,call=c['calculator_call_id'],target=str(key),report_read_at_s=report_times[mid],calc_started_at_s=c['started_at_s']))
        valid_chain=False
        for m in deliveries:
            if m['sender']!='Lead' or m['delivery_id'] not in REQUESTS.get(f,[]):continue
            qualified=[]
            for reply_id,hit in report_matches.items():
                if not hit:continue
                reply=next(z for z in deliveries if z['delivery_id']==reply_id)
                # A same-round reply may have been written BEFORE this request was read.
                sendturn=next(z for z in x['turns'] if z['role']=='Reporting' and z['tool_call']['name'] in ['send_message','report'] and reply['content'].endswith(z['tool_call']['arguments'].get('text','__missing__')))
                if m['read_at_turn'] is None or sendturn['turn_number']<m['read_at_turn']:continue
                earlier=set().union(*(h for mid,h in report_matches.items() if report_times[mid]<report_times[reply_id])) if any(report_times[mid]<report_times[reply_id] for mid in report_matches) else set()
                if any(k[2]!='profit_m' for k in hit-earlier):qualified.append(reply_id)
            valid_chain|=bool(qualified)
            requests.append(dict(family=f,delivery=m['delivery_id'],reporter_read_turn=m['read_at_turn'],subsequent_new_value_replies=';'.join(map(str,qualified)),content=m['content']))
        local_complete=sum(k[2]=='profit_m' for k in available)==4
        mid_complete=sum(k[2]!='profit_m' for k in available)==8
        company_complete=len(company_matches)==4
        wrong=not x['exact_optimum'];local_plan=e['labeled_local_plan'];assert local_plan!=x['optimal_plan']
        record=dict(family=f,org=org,run_id=r['run_id'],record_path=r['record_path'],exact=x['exact_optimum'],score=x['decision_score'],submitted=x['submitted_plan'],optimal=x['optimal_plan'],local_plan=local_plan,
            four_local_values=local_complete,eight_intermediate_values=mid_complete,four_company_values=company_complete,
            local_plan_selected=x['submitted_plan']==local_plan,failed_after_local=wrong and local_complete and not company_complete,
            failed_after_company=wrong and company_complete,other_failure=wrong and not local_complete and not company_complete,
            report_six_complete=len(report_all)==6 if org!='single' else None,new_values_after_opening=bool(new) if org!='single' else None,
            all_four_report_quantities_reused=len(reused)==4 if org!='single' else None,explicit_targeted_request=bool(REQUESTS.get(f)) if org!='single' else None,
            temporally_valid_request_reply=valid_chain if org!='single' else None,
            report_values_opening=len(opening),report_values_by_decision=len(report_all),new_report_values=len(new),company_values=len(company_matches))
        runs.append(record)
        for scale in [.1,1,10]:
            allvals=observed+report_values
            local=all(any(abs(v-truth)<tolerance(k[2],scale) for v in (allvals if k[0]==report_branch else observed)) for k,truth in targets.items() if k[2]=='profit_m')
            inter=all(any(abs(v-truth)<tolerance(k[2],scale) for v in (allvals if k[0]==report_branch else observed)) for k,truth in targets.items() if k[2]!='profit_m')
            comp=all(any(abs(v-truth)<.001*scale for v in allvals) for truth in company.values())
            sens.append(dict(family=f,org=org,scale=scale,four_local_values=local,eight_intermediate_values=inter,four_company_values=comp))
        if wrong:failure_context.append(record)
    d=pd.DataFrame(runs).sort_values(['family','org']);assert len(d)==204 and d.groupby('org').size().eq(102).all()
    assert d[['failed_after_local','failed_after_company','other_failure']].sum(axis=1).eq(~d.exact).all()
    base_sensitivity=pd.DataFrame(sens).query('scale==1').sort_values(['family','org'])
    assert np.array_equal(d[['four_local_values','eight_intermediate_values','four_company_values']].to_numpy(),base_sensitivity[['four_local_values','eight_intermediate_values','four_company_values']].to_numpy())
    metrics=['four_local_values','eight_intermediate_values','four_company_values','local_plan_selected','failed_after_local','failed_after_company']
    tests=pd.DataFrame([paired_test(d,m) for m in metrics]);tests['p_holm_six']=multipletests(tests.p_value,method='holm')[1]
    within=[];central=d[d.org=='centralized_two_way']
    for metric in ['report_six_complete','new_values_after_opening','all_four_report_quantities_reused']:
        yes=central[central[metric].eq(True)];no=central[central[metric].eq(False)]
        table=[[int(yes.exact.sum()),int((~yes.exact).sum())],[int(no.exact.sum()),int((~no.exact).sum())]]
        within.append(dict(metric=metric,yes_n=len(yes),yes_correct=int(yes.exact.sum()),no_n=len(no),no_correct=int(no.exact.sum()),p_value=fisher_exact(table).pvalue))
    within=pd.DataFrame(within);within['p_holm_three']=multipletests(within.p_value,method='holm')[1]
    for name,data in [('runs',d),('value_evidence',pd.DataFrame(evidence)),('requests',pd.DataFrame(requests)),('report_messages',pd.DataFrame(messages)),('quantity_reuse',pd.DataFrame(reuse)),('mechanism_tests',tests),('within_central_tests',within),('sensitivity',pd.DataFrame(sens)),('all_failures',pd.DataFrame(failure_context))]:data.to_csv(HERE/f'{name}.csv',index=False)
    print(tests.to_string(index=False));print(within.to_string(index=False));print('Central request and chain counts:',central[['explicit_targeted_request','temporally_valid_request_reply','new_values_after_opening','report_six_complete','all_four_report_quantities_reused']].sum().to_dict());print('Final exact outcome:',paired_test(d,'exact'))
    print('Failure partition:',d.groupby('org')[['failed_after_local','failed_after_company','other_failure','local_plan_selected']].sum().to_dict())

if __name__=='__main__':main()
