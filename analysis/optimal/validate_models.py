"""Independent numerical checks of the primary logit and probability contrasts."""
import json
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from patsy import build_design_matrices
from scipy.special import expit
from run_optimal_logit import HERE, BASE, LOGIT, ORGANIZATIONS, fit_logit

d=pd.read_csv(HERE/'logit_regression_data.csv')
formula=BASE.replace('score ~','optimal ~')+LOGIT['M4']
r=fit_logit(formula,d)
alt=smf.logit(formula,d).fit(disp=False,maxiter=150,tol=1e-10,
    cov_type='cluster',cov_kwds={'groups':d.family_id,'use_correction':True})
assert alt.mle_retvals['converged']
assert np.allclose(r.params,alt.params,atol=1e-8)
assert np.allclose(r.cov_params(),alt.cov_params(),atol=1e-7)
xs=[]
for org,rho in [('centralized_two_way',1),('mutual',1),('centralized_two_way',0),('mutual',0)]:
    a,c,k=ORGANIZATIONS[org]
    grid=d.drop_duplicates('family_id').assign(authority=a,communication=c,commitment=k,rho=rho)
    xs.append(np.asarray(build_design_matrices([r.model.data.design_info],grid)[0]))
signs=[1,-1,-1,1]
def value(beta):return sum(s*expit(x@beta).mean() for s,x in zip(signs,xs))
beta=np.asarray(r.params)
grad=sum(s*(x*(expit(x@beta)*(1-expit(x@beta)))[:,None]).mean(axis=0) for s,x in zip(signs,xs))
eps=1e-6;numeric=[]
for j in range(len(beta)):
    h=np.zeros_like(beta);h[j]=eps;numeric.append((value(beta+h)-value(beta-h))/(2*eps))
err=float(max(abs(grad-np.array(numeric))))
assert err<1e-8
se=float(np.sqrt(grad@r.cov_params()@grad))
saved=pd.read_csv(HERE/'logit_selected_contrasts.csv')
v=saved[(saved.model=='M4')&(saved.rho=='change')&(saved['first']=='centralized_two_way')&(saved['second']=='mutual')].iloc[0]
assert np.isclose(value(beta),v.probability_difference_estimate,atol=1e-10)
assert np.isclose(se,v.probability_difference_cluster_se,atol=1e-10)
report=dict(discrete_logit_coefficient_max_difference=float(max(abs(r.params-alt.params))),
            discrete_logit_covariance_max_difference=float(np.max(abs(r.cov_params()-alt.cov_params()).to_numpy())),
            probability_delta_gradient_max_difference=err,
            reproduced_probability_endpoint_change=float(value(beta)),reproduced_cluster_se=se,
            logit_n=len(d),logit_families=d.family_id.nunique())
(HERE/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
