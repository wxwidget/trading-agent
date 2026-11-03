"""Convex portfolio targets with scipy; monthly execution remains original."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import core,previous
P=Path(__file__).resolve().parent
MODELS=('reference','minrisk_solver','momentum_solver','fast_control')
ORIGINAL_TARGET=core.target

def load_data(folder):
 d=core.load_data(folder);mask=d.tradable.copy()
 for c in core.CODES:
  suffix='_raw.csv' if c.startswith('sh') else '_sina.csv'
  raw=pd.read_csv(Path(folder)/f'{c}{suffix}',index_col=0,parse_dates=True).reindex(d.tr.index)
  mask[c]&=raw.volume.notna()&(raw.volume>0)
 return core.Data(d.open,d.close,d.div,d.tr,mask)

def optimize(covs,score,gross,budget,kind):
 """All arrays contain chosen assets only. Returns weights, numeric audit."""
 n=len(score);q=[cov/budget**2 for cov in covs]
 equal=np.full(n,gross/n)
 if kind=='minrisk_solver':
  # z bounds normalized squared portfolio risk, i.e. variance/budget^2.
  x0=np.r_[equal,max(equal@a@equal for a in q)]
  constraints=[{'type':'eq','fun':lambda x:np.sum(x[:n])-gross,
                'jac':lambda x:np.r_[np.ones(n),0.]}]
  for a in q:
   constraints.append({'type':'ineq','fun':lambda x,a=a:x[-1]-x[:n]@a@x[:n],
                       'jac':lambda x,a=a:np.r_[-2*a@x[:n],1.]})
  result=minimize(lambda x:x[-1],x0,jac=lambda x:np.r_[np.zeros(n),1.],
    bounds=[(0,gross)]*n+[(0,None)],constraints=constraints,
    method='SLSQP',options={'ftol':1e-9,'maxiter':200})
  w=np.clip(result.x[:n],0,gross)
  raw_risk=np.sqrt(max(w@a@w for a in covs))
  if raw_risk>budget:w*=budget/raw_risk
 else:
  preference=score/max(float(score.max()),1e-12)
  risk=np.sqrt(max(equal@a@equal for a in covs))
  x0=equal*min(1.,budget/max(risk,1e-12))
  constraints=[{'type':'ineq','fun':lambda x:gross-x.sum(),'jac':lambda x:-np.ones(n)}]
  for a in q:
   constraints.append({'type':'ineq','fun':lambda x,a=a:1.-x@a@x,
                       'jac':lambda x,a=a:-2*a@x})
  result=minimize(lambda x:-preference@x,x0,jac=lambda x:-preference,
    bounds=[(0,gross)]*n,constraints=constraints,method='SLSQP',
    options={'ftol':1e-9,'maxiter':200})
  w=np.clip(result.x,0,gross)
 risk=np.sqrt(max(0.,max(w@a@w for a in covs)))
 # Numerical feasibility check separate from optimizer success flag.
 feasible=bool(np.isfinite(w).all() and w.sum()<=gross+1e-7 and risk<=budget+1e-7)
 if kind=='minrisk_solver':
  raw=result.x[:n];z=result.x[-1]
  feasible=feasible and abs(raw.sum()-gross)<1e-7 and all(z-raw@a@raw>=-1e-7 for a in q)
 return w,{'solver_success':bool(result.success),'feasible':bool(feasible),
           'solver_message':str(result.message),'iterations':int(result.nit),
           'objective':float(result.fun)}

def target(d,date,cfg,model):
 reference,old=previous.target(d,date,cfg,'combined')
 if model=='fast_control':return previous.target(d,date,cfg,'fast_risk')
 if model=='reference':return reference,{'fallback':False,'solver_success':True,**old}
 selected=np.flatnonzero(reference>0)
 if not len(selected):return reference,{'fallback':False,'solver_success':True,'solver_message':'no eligible assets'}
 h=d.tr.loc[:date];m=h.groupby(h.index.to_period('M')).last()
 score=(sum(m.iloc[-1]/m.iloc[-k-1]-1 for k in cfg.horizons)/len(cfg.horizons)).to_numpy()[selected]
 ret=h.pct_change().dropna()
 covs=[ret.tail(n).cov().to_numpy()[np.ix_(selected,selected)]*252 for n in (21,126)]
 try:
  small,info=optimize(covs,score,.5*len(selected),cfg.vol_target,model)
 except (ValueError,FloatingPointError,np.linalg.LinAlgError) as e:
  return reference,{'fallback':True,'solver_success':False,'solver_message':str(e)}
 fallback=not (info['solver_success'] and info['feasible'])
 w=reference.copy() if fallback else np.zeros(len(core.CODES))
 if not fallback:w[selected]=small
 full_covs=[ret.tail(n).cov().to_numpy()*252 for n in (21,126)]
 return w,{**info,'fallback':fallback,'forecast_vol21':float(np.sqrt(max(0,w@full_covs[0]@w))),
           'forecast_vol126':float(np.sqrt(max(0,w@full_covs[1]@w))),'cash':float(1-w.sum())}

def run(d,model,cost=.0003,delay=0,begin='2016-10-28',end='2026-10-28',exclude_gold=False):
 if model not in MODELS:raise ValueError(model)
 audit=[]
 def hook(data,date,cfg):
  w,info=target(data,date,cfg,model)
  audit.append({'signal_date':date,**{c:float(x) for c,x in zip(core.CODES,w)},**info})
  return w,info
 core.target=hook
 try:r=core.simulate(d,core.Config(stop=None,vol_target=.10,cost=cost,delay=delay,exclude_gold=exclude_gold),begin,end)
 finally:core.target=ORIGINAL_TARGET
 return r,pd.DataFrame(audit)

def main():
 d=load_data(P/'data');out=P/'outputs';out.mkdir(exist_ok=True)
 rows=[];curves={};money={};latest=[]
 last_month_end=d.tr.index[d.tr.index.to_period('M')<d.tr.index[-1].to_period('M')][-1]
 for model in MODELS:
  r,a=run(d,model);metrics=core.metrics(r)
  rows.append({'model':model,'case':'full',**metrics,'fallbacks':int(a.get('fallback',pd.Series(dtype=bool)).sum())})
  curves[model]=r.equity;money[model]=previous.money_scenario(r)
  r.weights.to_csv(out/f'{model}_weights.csv');r.trades.to_csv(out/f'{model}_trades.csv',index=False)
  a.to_csv(out/f'{model}_solver_audit.csv',index=False)
  w,info=target(d,last_month_end,core.Config(stop=None,vol_target=.10),model)
  latest.append({'model':model,'signal_date':str(last_month_end.date()),**dict(zip(core.CODES,w)),'cash':1-w.sum()})
  print(model,json.dumps(metrics),'fallbacks',rows[-1]['fallbacks'],flush=True)
  for case,kw in [('cost_0.1pct',{'cost':.001}),('delay_1',{'delay':1}),
    ('2017_2019',{'begin':'2017-01-03','end':'2019-12-31'}),
    ('2020_2022',{'begin':'2020-01-02','end':'2022-12-30'}),('2023_end',{'begin':'2023-01-03'})]:
   rr,aa=run(d,model,**kw)
   rows.append({'model':model,'case':case,**core.metrics(rr),'fallbacks':int(aa.get('fallback',pd.Series(dtype=bool)).sum())})
 pd.DataFrame(curves).to_csv(out/'equity.csv');pd.DataFrame(rows).to_csv(out/'metrics.csv',index=False)
 pd.DataFrame(latest).to_csv(out/'last_complete_signal_targets.csv',index=False)
 (out/'money_scenario.json').write_text(json.dumps(money,indent=2))
if __name__=='__main__':main()
