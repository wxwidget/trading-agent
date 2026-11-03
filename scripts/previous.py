"""Bounded improvements to existing momentum; python research.py."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import core

P=Path(__file__).resolve().parent
ORIGINAL_TARGET=core.target
MODELS=('base','inverse_vol','fast_risk','combined')

def target(d,date,cfg,model):
    # Reuse original ranking/eligibility exactly. Undo its volatility scaling
    # only by reconstructing the actual selected slots from positive weights.
    original,info=ORIGINAL_TARGET(d,date,cfg)
    chosen=np.flatnonzero(original>0)
    w=np.zeros(len(core.CODES));w[chosen]=.5
    returns=d.tr.loc[:date].pct_change().dropna()
    cov=returns.tail(cfg.risk_days).cov().to_numpy()*252
    if model in ('inverse_vol','combined') and len(chosen)>1:
        sigma=np.sqrt(np.diag(cov))[chosen]
        inv=1/np.maximum(sigma,1e-8)
        w[chosen]=.5*len(chosen)*inv/inv.sum()
    long_vol=np.sqrt(max(0.,float(w@cov@w)))
    short_cov=returns.tail(21).cov().to_numpy()*252
    short_vol=np.sqrt(max(0.,float(w@short_cov@w)))
    risk=max(long_vol,short_vol) if model in ('fast_risk','combined') else long_vol
    scale=min(1.,cfg.vol_target/risk) if risk>0 else 1.
    return w*scale,{**info,'long_vol':long_vol,'short_vol':short_vol,'scale':scale}

def run(d,model,cost=.0003,delay=0,begin='2016-10-28',end='2026-10-28'):
    if model not in MODELS:raise ValueError(model)
    core.target=lambda data,date,cfg:target(data,date,cfg,model)
    try:
        return core.simulate(d,core.Config(stop=None,vol_target=.10,cost=cost,delay=delay),begin,end)
    finally:core.target=ORIGINAL_TARGET

def path_stats(eq,begin,end):
    p=pd.concat([pd.Series([1.]),eq.reset_index(drop=True)])
    ret=p.pct_change().dropna()
    return {'cagr':float(eq.iloc[-1]**(365.25/(end-begin).days)-1),
            'max_drawdown':float((p/p.cummax()-1).min()),
            'volatility':float(ret.std()*np.sqrt(252))}

def money_scenario(r,rate=.02):
    days=r.equity.index.to_series().diff().dt.days.fillna(0)
    ret=r.equity.pct_change();ret.iloc[0]=r.equity.iloc[0]-1
    cash=r.weights.cash.shift().fillna(1)
    eq=(1+ret+cash*((1+rate)**(days/365.25)-1)).cumprod()
    return path_stats(eq,r.start,r.end)

def main():
    out=P/'outputs';out.mkdir(exist_ok=True)
    d=core.load_data(P/'data');rows=[];curves={};money={}
    for model in MODELS:
        r=run(d,model);m=core.metrics(r)
        rows.append({'model':model,'case':'full',**m});curves[model]=r.equity
        r.weights.to_csv(out/f'{model}_weights.csv');r.trades.to_csv(out/f'{model}_trades.csv',index=False)
        money[model]=money_scenario(r)
        print(model,json.dumps(m),flush=True)
        for label,kwargs in [('cost_0.1pct',{'cost':.001}),('delay_1',{'delay':1}),
                ('2017_2019',{'begin':'2017-01-03','end':'2019-12-31'}),
                ('2020_2022',{'begin':'2020-01-02','end':'2022-12-30'}),
                ('2023_end',{'begin':'2023-01-03'})]:
            rr=run(d,model,**kwargs);rows.append({'model':model,'case':label,**core.metrics(rr)})
    base=run(d,'base');control=.8*base.equity+.2
    rows.append({'model':'base80_cash20','case':'full',**path_stats(control,base.start,base.end)})
    curves['base80_cash20']=control
    pd.DataFrame(curves).to_csv(out/'equity.csv')
    pd.DataFrame(rows).to_csv(out/'metrics.csv',index=False)
    (out/'money_scenario.json').write_text(json.dumps(money,indent=2))
    yearly=pd.DataFrame(curves).groupby(pd.DataFrame(curves).index.year).last()
    yearly=yearly.pct_change().iloc[1:];yearly.to_csv(out/'calendar_returns.csv')
if __name__=='__main__':main()
