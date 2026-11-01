"""Summarize the conservative trace and the reviewed decision-time messages."""
from pathlib import Path
import pandas as pd
from scipy.stats import binomtest, fisher_exact
from statsmodels.stats.multitest import multipletests
P=Path(__file__).resolve().parent
# Manual coding of the 150 pre-decision messages in report_texts.csv.
# These four explicitly name a best COMPANY pair, not just a preferred branch policy.
RECOMMEND={4:(4,'BA'),27:(4,'AA'),34:(6,'AA'),41:(4,'AA')}
# No read message with a company-comparison reminder in these five runs.
NO_REMINDER={20,23,39,68,96}
# Explicit best-pair recommendations sent but not read before filing (report_texts.csv).
UNREAD={2:'BB',5:'BA',7:'BA',10:'AA',14:'AB',26:'AB',30:'AB',48:'BA',50:'BB',51:'AA',53:'BB',56:'BA',66:'BA',75:'AA',79:'AA',100:'BB'}
d=pd.read_csv(P/'runs.csv');d['identified_ranking_action_break']=d.ranking_correct&~d.follows_ranking
d['interaction_attempt']=d.interaction_expressions>0
m=pd.read_csv(P/'report_texts.csv');ledger=[]
for _,r in d[d.org=='centralized_two_way'].iterrows():
 read=m[(m.family==r.family)&m.read];rec=RECOMMEND.get(r.family)
 assert len(read)>0
 if rec:assert len(read[read.delivery==rec[0]])==1
 ledger.append(dict(family=r.family,company_objective_reminder=r.family not in NO_REMINDER,
     explicit_best_pair=rec[1] if rec else '',recommendation_delivery=rec[0] if rec else '',
     recommendation_correct=rec[1]==r.optimal if rec else None,submitted_recommendation=rec[1]==r.submitted if rec else None,
     unread_best_pair=UNREAD.get(r.family,''),source_deliveries=';'.join(map(str,read.delivery)),
     exact=r.exact,submitted=r.submitted,optimal=r.optimal))
l=pd.DataFrame(ledger);l.to_csv(P/'message_coding.csv',index=False)
metrics=['interaction_attempt','complete_comparison','ranking_correct','identified_ranking_action_break','ranking_revised_to_optimal'];tests=[]
for metric in metrics:
 w=d.pivot(index='family',columns='org',values=metric);a=w.single;b=w.centralized_two_way
 sa=int((a&~b).sum());ca=int((b&~a).sum())
 tests.append(dict(metric=metric,single=int(a.sum()),central=int(b.sum()),single_only=sa,central_only=ca,p_value=binomtest(sa,sa+ca).pvalue if sa+ca else 1.))
t=pd.DataFrame(tests);t['p_holm_five']=multipletests(t.p_value,method='holm')[1]
old=pd.read_csv(P.parent/'rho1_audit/mechanism_tests.csv')
t['p_holm_eleven']=multipletests(list(old.p_value)+list(t.p_value),method='holm')[1][-5:]
t.to_csv(P/'process_tests.csv',index=False);d.to_csv(P/'runs_coded.csv',index=False)
w=d.pivot(index='family',columns='org',values='complete_comparison');both=w[w.all(axis=1)].index
common=d[d.family.isin(both)];z=common.pivot(index='family',columns='org',values='identified_ranking_action_break');sa=int((z.single&~z.centralized_two_way).sum());ca=int((~z.single&z.centralized_two_way).sum())
print(t.to_string(index=False));print('Both traceable:',len(both),'breaks',z.sum().to_dict(),'p',binomtest(sa,sa+ca).pvalue if sa+ca else 1)
print('Message summaries:',l.company_objective_reminder.sum(),'read best-pair',l.explicit_best_pair.ne('').sum(),'unread best-pair',l.unread_best_pair.ne('').sum())
print('Reminder outcome:',l.groupby('company_objective_reminder').exact.agg(['sum','count']).to_dict())
assert len(d)==204 and not d.duplicated(['family','org']).any()
assert d.groupby('family').size().eq(2).all()
assert d[d.ranking_correct&d.follows_ranking].exact.all()
