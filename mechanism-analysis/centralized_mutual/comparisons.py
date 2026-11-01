"""Conservative reconstruction of decision-maker company payoff comparisons."""
import ast,json
from pathlib import Path
import pandas as pd
P=Path(__file__).resolve().parent;DATA=P.parents[1]/'data';d=pd.read_csv(P/'runs.csv');out=[];ev=[]
def nums(n):return [z.value for z in ast.walk(n) if isinstance(z,ast.Constant) and isinstance(z.value,(int,float))]
def close(a,b):return abs(a-b)<.0001
for _,r in d[d.rho==1].iterrows():
 x=json.loads((DATA/r.record_path).read_text())['result'];e=x['economic_family'];roles=['Lead'] if r.org=='centralized_two_way' else ['Branch 1 Specialist','Branch 2 Specialist']
 turn_rounds={(t['role'],t['turn_number']):t['round_number'] for t in x['turns']}
 aligned=[''.join(e['label_maps'][j][p] for j in [0,1]) for p in ['standard','premium']]
 for role in roles:
  cut=next(t['completed_at_s'] for t in x['turns'] if t['role']==role and t['tool_call']['name'] in ['submit_branch','submit_company']);fixed=[(v['fixed_cost_m'],(j,e['label_maps'][j][p])) for j,l in enumerate(e['local']) for p,v in l.items()];anchors=[(v['profit_m'],(j,e['label_maps'][j][p])) for j,l in enumerate(e['local']) for p,v in l.items()];special=[e['interaction_primitives'][k] for k in ['market_integration_index','coherence_bonus_per_unit','mismatch_penalty_per_unit','migration_rate']]
  def inter(n):return any(close(abs(v),a) for v in nums(n) for a in special)
  def labels(n):
   z=set()
   for a in ast.walk(n):
    if isinstance(a,ast.BinOp) and isinstance(a.op,ast.Sub) and isinstance(a.right,ast.Constant):z|={k for v,k in fixed if close(a.right.value,v)}
   for v in nums(n):z|={k for a,k in anchors if close(a,v)}
   return z
  def base(n):
   if not inter(n):return [n]
   if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Sub)):return base(n.left)+base(n.right)
   return []
  latest={};ninter=0
  for c in sorted(x['calculator_calls'],key=lambda c:c['completed_at_s']):
   if c['completed_at_s']>=cut:continue
   for i,v in enumerate(c['output'].get('results',[]),1):
    expr=v.get('expression','');value=v.get('value')
    if not isinstance(value,(int,float)):continue
    try:n=ast.parse(expr,mode='eval').body
    except SyntaxError:continue
    if not inter(n):
     lab=labels(n);hasfixed=any(isinstance(a,ast.BinOp) and isinstance(a.op,ast.Sub) and isinstance(a.right,ast.Constant) and any(close(a.right.value,z) for z,k in fixed) for a in ast.walk(n))
     if (hasfixed or len({k[0] for k in lab})==2) and all(len({p for j,p in lab if j==k})<=1 for k in [0,1]):anchors.extend((value,k) for k in lab)
    if c['role']!=role or not inter(n):continue
    ninter+=1;lab=set().union(*(labels(z) for z in base(n)))
    pair=''.join(next(iter({p for j,p in lab if j==k})) for k in [0,1]) if all(len({p for j,p in lab if j==k})==1 for k in [0,1]) else ''
    ev.append(dict(family=r.family,org=r.org,role=role,call=c['calculator_call_id'],item=i,pair=pair,value=value,expression=expr,time=c['completed_at_s'],round=turn_rounds[(c['role'],c['model_turn_number'])]))
    if pair:latest[pair]=value
  full=len(latest)==4;two=all(p in latest for p in aligned);best=max(latest,key=latest.get) if full else '';aligned_best=max(aligned,key=lambda p:latest[p]) if two else '';own_branch=int(role[7])-1 if role.startswith('Branch ') else None
  out.append(dict(family=r.family,org=r.org,role=role,all_four=full,computed_best=best,aligned_comparison=two,aligned_best=aligned_best,ranking_correct=full and best==r.optimal,aligned_ranking_correct=two and aligned_best==r.optimal,final=r.final,optimal=r.optimal,exact=r.exact,own_action_matches_computed_best=(r.final==best if own_branch is None else r.final[own_branch]==best[own_branch]) if full else None,interaction_outputs=ninter))
a=pd.DataFrame(out);a.to_csv(P/'decisionmaker_comparisons.csv',index=False);pd.DataFrame(ev).to_csv(P/'comparison_expressions.csv',index=False)
print(a.groupby(['org','role'])[['all_four','ranking_correct','aligned_comparison','aligned_ranking_correct']].sum().to_string())
m=a[a.org=='mutual'];w=m.pivot(index='family',columns='role',values='aligned_best').fillna('');w.columns=['b1','b2'];both=w.b1.ne('')&w.b2.ne('');same=both&w.b1.eq(w.b2);conflict=both&~same
print('Mutual both aligned comparisons',both.sum(),'same',same.sum(),'conflict',conflict.sum());print('conflict families',w[conflict].to_dict('index'))
