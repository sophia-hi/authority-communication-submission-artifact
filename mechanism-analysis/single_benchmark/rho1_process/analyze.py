"""Observable company comparison -> submission; conservative expression tracing."""
import ast,json,re
from pathlib import Path
import pandas as pd
from scipy.stats import binomtest
from statsmodels.stats.multitest import multipletests
P=Path(__file__).resolve().parent
D=P.parents[2]/'data'

def nums(node):
    return [n.value for n in ast.walk(node) if isinstance(n,ast.Constant) and isinstance(n.value,(int,float))]
def close(a,b):return abs(a-b)<1e-4

def main():
    idx=json.loads((D/'combined_exploratory_3570_index.json').read_text())['rows']
    rows=[];ev=[];texts=[]
    for r in idx:
        if r['rho']!=1 or r['organization'] not in ['single','centralized_two_way']:continue
        x=json.loads((D/r['record_path']).read_text())['result'];e=x['economic_family'];f=x['family_id'];org=x['organization'];role='Owner' if org=='single' else 'Lead'
        cutoff=next(t['completed_at_s'] for t in x['turns'] if t['role']==role and t['tool_call']['name']=='submit_company')
        fixed=[(v['fixed_cost_m'],(j,e['label_maps'][j][p])) for j,l in enumerate(e['local']) for p,v in l.items()]
        anchors=[(v['profit_m'],(j,e['label_maps'][j][p])) for j,l in enumerate(e['local']) for p,v in l.items()]
        ip=e['interaction_primitives'];special=[ip[k] for k in ['market_integration_index','coherence_bonus_per_unit','mismatch_penalty_per_unit','migration_rate']]
        def isinteraction(n):return any(close(abs(v),t) for v in nums(n) for t in special)
        def labels(n):
            out=set()
            for a in ast.walk(n):
                if isinstance(a,ast.BinOp) and isinstance(a.op,ast.Sub) and isinstance(a.right,ast.Constant):
                    out|={k for v,k in fixed if close(a.right.value,v)}
            for v in nums(n):out|={k for a,k in anchors if close(a,v)}
            return out
        def baseparts(n):
            if not isinteraction(n):return [n]
            if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Sub)):
                return baseparts(n.left)+baseparts(n.right)
            return [] if isinteraction(n) else [n]
        own=[];n_interaction=0;unmapped=[]
        for c in sorted(x['calculator_calls'],key=lambda z:z['completed_at_s']):
            if c['completed_at_s']>=cutoff:continue
            for i,v in enumerate(c['output'].get('results',[]),1):
                expr=v.get('expression','');value=v.get('value')
                if not isinstance(value,(int,float)):continue
                try:n=ast.parse(expr,mode='eval').body
                except SyntaxError:continue
                if not isinteraction(n):
                    lab=labels(n)
                    # A subtract-fixed-cost expression identifies local profits, including erroneous ones.
                    hasfixed=any(isinstance(a,ast.BinOp) and isinstance(a.op,ast.Sub) and isinstance(a.right,ast.Constant) and any(close(a.right.value,z) for z,k in fixed) for a in ast.walk(n))
                    if hasfixed or len({k[0] for k in lab})==2:
                        if all(len({p for j,p in lab if j==k})<=1 for k in [0,1]):
                            anchors.extend((value,k) for k in lab)
                if c['role']!=role or not isinteraction(n):continue
                n_interaction+=1
                lab=set().union(*(labels(z) for z in baseparts(n)))
                pair=''.join(next(iter({p for j,p in lab if j==k})) for k in [0,1]) if all(len({p for j,p in lab if j==k})==1 for k in [0,1]) else ''
                row=dict(family=f,org=org,call=c['calculator_call_id'],item=i,time=c['completed_at_s'],pair=pair,value=value,expression=expr,base_labels=str(sorted(lab)))
                ev.append(row)
                if pair:own.append(row)
                else:unmapped.append(row)
        latest={};snapshots=[]
        for call in dict.fromkeys(a['call'] for a in own):
            for a in own:
                if a['call']==call:latest[a['pair']]=a
            if len(latest)==4:
                snapshots.append((call,max(latest,key=lambda p:latest[p]['value'])))
        full=len(latest)==4
        best=max(latest,key=lambda p:latest[p]['value']) if full else ''
        read=[m for m in x['protocol_deliveries'] if m['sender']=='Reporting' and m['recipient']=='Lead' and m['read_at_s'] is not None and m['read_at_s']<cutoff and m['decision_delivery_status']=='delivered_before_decision']
        rows.append(dict(family=f,org=org,exact=x['exact_optimum'],submitted=x['submitted_plan'],optimal=x['optimal_plan'],local=e['labeled_local_plan'],interaction_expressions=n_interaction,mapped_company_expressions=len(own),mapped_pairs=len(latest),complete_comparison=full,first_computed_best=snapshots[0][1] if snapshots else '',ranking_revised_to_optimal=bool(snapshots) and snapshots[0][1]!=x['optimal_plan'] and best==x['optimal_plan'],computed_best=best,ranking_correct=full and best==x['optimal_plan'],follows_ranking=full and best==x['submitted_plan'],read_reports=len(read),record_path=r['record_path']))
        if org!='single':
            for m in x['protocol_deliveries']:
                if m['sender']=='Reporting':
                    content=re.sub(r'^.*?Reporting message: ','',m['content'],flags=re.S)
                    texts.append(dict(family=f,delivery=m['delivery_id'],read=m in read,content=content))
    d=pd.DataFrame(rows).sort_values(['family','org']);v=pd.DataFrame(ev)
    d.to_csv(P/'runs.csv',index=False);v.to_csv(P/'expression_trace.csv',index=False);pd.DataFrame(texts).to_csv(P/'report_texts.csv',index=False)
    for org,g in d.groupby('org'):
        print(org,len(g),'interaction',sum(g.interaction_expressions>0),'full',g.complete_comparison.sum(),'correct rank',g.ranking_correct.sum(),'follows',g.follows_ranking.sum())
        print(pd.crosstab([g.complete_comparison,g.ranking_correct,g.follows_ranking],g.exact))
if __name__=='__main__':main()
