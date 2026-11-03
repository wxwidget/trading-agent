"""Five user-selected ETFs, cash fallback, close-based portfolio stop.
No broker API; continuous units and modeled open fills. See README for limits.
"""
from pathlib import Path
from dataclasses import dataclass,replace
import json
import pandas as pd
import numpy as np
CODES=('sh510300','sz159915','sh510880','sh518880','sz159920')
@dataclass(frozen=True)
class Config:
    stop: float|None=.08
    cooldown: int=20
    cost: float=.0003
    delay: int=0
    vol_target: float=.15
    risk_days: int=126
    band: float=.05
    horizons: tuple=(3,6,12)
    exclude_gold: bool=False

@dataclass
class Data:
    open:pd.DataFrame
    close:pd.DataFrame
    div:pd.DataFrame
    tr:pd.DataFrame
    tradable:pd.DataFrame

@dataclass
class Result:
    equity:pd.Series
    trades:pd.DataFrame
    weights:pd.DataFrame
    events:pd.DataFrame
    states:pd.DataFrame
    start:pd.Timestamp
    end:pd.Timestamp

def load_data(folder,end='2026-10-30'):
    folder=Path(folder);prices={};opens={};divs={}
    for c in ['sh510300','sh510880','sh518880']:
        raw=pd.read_csv(folder/f'{c}_raw.csv',index_col=0,parse_dates=True).loc[:end]
        adj=pd.read_csv(folder/f'{c}.csv',index_col=0,parse_dates=True).loc[:end]
        for col in ['open','high','low']:
            assert ((adj[col]-raw[col])-(adj.close-raw.close)).dropna().abs().max()<.0021
        dc=(adj.close-raw.close).round(3).diff().fillna(0).round(3)
        assert not (dc<-.003).any()
        prices[c]=raw.close;opens[c]=raw.open;divs[c]=dc.where(dc>.003,0.)
    for c in ['sz159915','sz159920']:
        raw=pd.read_csv(folder/f'{c}_sina.csv',index_col=0,parse_dates=True).loc[:end]
        prices[c]=raw.close;opens[c]=raw.open;divs[c]=pd.Series(0.,index=raw.index)
        if c=='sz159920':divs[c].loc['2018-06-22']=.076
    dates=prices['sh510300'].index;start=max(v.index.min() for v in prices.values());dates=dates[dates>=start]
    close=pd.DataFrame(prices).reindex(index=dates,columns=CODES)
    op=pd.DataFrame(opens).reindex(index=dates,columns=CODES)
    div=pd.DataFrame(divs).reindex(index=dates,columns=CODES).fillna(0.)
    tradable=close.notna()&op.notna();close=close.ffill();op=op.fillna(close.shift())
    assert not close.isna().any().any() and not op.isna().any().any()
    tr=((close+div)/close.shift()).fillna(1.).cumprod()
    assert not (tr.pct_change().abs()>.25).any().any()
    return Data(op,close,div,tr,tradable)

def target(data,date,cfg):
    h=data.tr.loc[:date];m=h.groupby(h.index.to_period('M')).last()
    assert len(m)>=13
    score=sum(m.iloc[-1]/m.iloc[-k-1]-1 for k in cfg.horizons)/len(cfg.horizons)
    eligible=(score>0)&(m.iloc[-1]>m.tail(10).mean())
    if cfg.exclude_gold:eligible['sh518880']=False
    # One mainland equity representative; Hong Kong and gold are separate categories.
    mainland=[c for c in ['sh510300','sz159915','sh510880'] if eligible[c]]
    candidates=[max(mainland,key=lambda c:score[c])] if mainland else []
    candidates += [c for c in ['sh518880','sz159920'] if eligible[c]]
    picks=sorted(candidates,key=lambda c:score[c],reverse=True)[:2]
    w=np.zeros(len(CODES))
    for c in picks:w[CODES.index(c)]=.5
    cov=h.pct_change().dropna().tail(cfg.risk_days).cov().to_numpy()*252
    vol=float(np.sqrt(max(0.,w@cov@w)))
    scale=min(1.,cfg.vol_target/vol) if vol>0 else 1.
    return w*scale,{**{f'score_{c}':score[c] for c in CODES},'eligible':int(eligible.sum()),'forecast_vol_before_scale':vol,'scale':scale}

def execute(qty,cash,price,w,cost):
    values=qty*price;nav=float(values.sum()+cash);after=nav
    for _ in range(20):after=nav-cost*np.abs(w*after-values).sum()
    amount=w*after-values;fee=float(cost*np.abs(amount).sum())
    q=w*after/price;c=float((1-w.sum())*after)
    assert abs(q@price+c+fee-nav)<1e-10*max(1.,nav)
    return q,c,fee,float(np.abs(amount).sum()/nav),nav

def simulate(d,cfg=Config(),begin='2016-10-28',end='2026-10-28'):
    idx=d.close.index;active=idx[(idx>=begin)&(idx<=end)];assert len(active)
    qty=np.zeros(len(CODES));cash=1.;peak=1.;last_exit=None;pending=None
    eq=[];trades=[];weights=[];events=[];states=[]
    first=active[0];prevmonth=idx[idx.to_period('M')<first.to_period('M')][-1]
    w,info=target(d,prevmonth,cfg)
    if w.sum()>0:pending={'due':cfg.delay,'w':w,'reason':'initial','signal':prevmonth}
    for i,date in enumerate(active):
        cash+=float(qty@d.div.loc[date].to_numpy())
        if pending is not None and i>=pending['due']:
            needed=(qty>1e-12)|(pending['w']>1e-12)
            if not (needed&~d.tradable.loc[date].to_numpy()).any():
                before=bool(qty.sum()>1e-12)
                qty,cash,fee,turn,nav_open=execute(qty,cash,d.open.loc[date].to_numpy(),pending['w'],cfg.cost)
                after=bool(qty.sum()>1e-12)
                if after and not before:peak=nav_open # reset only at reentry; fee is counted
                if before and not after:last_exit=i
                trades.append({'date':date,'signal_date':pending['signal'],'reason':pending['reason'],'fee':fee,'turnover':turn,**{f'{c}_target':weight for c,weight in zip(CODES,pending['w'])},'cash_target':1-pending['w'].sum()})
                pending=None
        nav=float(qty@d.close.loc[date].to_numpy()+cash)
        invested=bool(qty.sum()>1e-12)
        if invested:peak=max(peak,nav)
        cycle_dd=nav/peak-1 if invested else 0.
        # Stop is observed only at close and always outranks the ordinary monthly order.
        if cfg.stop is not None and invested and cycle_dd<=-cfg.stop:
            if pending is None or pending['reason']!='stop':
                pending={'due':i+1+cfg.delay,'w':np.zeros(len(CODES)),'reason':'stop','signal':date}
                events.append({'date':date,'event':'stop_signal','nav':nav,'cycle_peak':peak,'cycle_drawdown':cycle_dd})
        loc=idx.get_loc(date)
        month_end=loc+1<len(idx) and idx[loc+1].to_period('M')!=date.to_period('M')
        if month_end and (pending is None or pending['reason']!='stop'):
            w,info=target(d,date,cfg)
            if invested:
                current=qty*d.close.loc[date].to_numpy()/nav
                required=np.max(np.abs(w-current))>=cfg.band-1e-12
                if required:pending={'due':i+1+cfg.delay,'w':w,'reason':'monthly' if w.sum()>0 else 'market_exit','signal':date}
            elif pending is None:
                cooled=last_exit is None or i-last_exit>=cfg.cooldown
                if cooled and w.sum()>0:
                    pending={'due':i+1+cfg.delay,'w':w,'reason':'reentry','signal':date}
                    events.append({'date':date,'event':'reentry_signal','nav':nav,'cycle_peak':peak,'cycle_drawdown':0.})
        eq.append((date,nav));weights.append((date,*(qty*d.close.loc[date].to_numpy()/nav),cash/nav))
        states.append((date,invested,peak,cycle_dd,last_exit if last_exit is not None else -1,pending['reason'] if pending else 'none'))
    return Result(pd.Series(dict(eq)),pd.DataFrame(trades),pd.DataFrame(weights,columns=['date',*CODES,'cash']).set_index('date'),pd.DataFrame(events),pd.DataFrame(states,columns=['date','invested','cycle_peak','cycle_drawdown','exit_session','pending']).set_index('date'),active[0],active[-1])

def metrics(r):
    eq=r.equity;path=pd.concat([pd.Series([1.],index=[r.start-pd.Timedelta(seconds=1)]),eq]);ret=eq.pct_change();ret.iloc[0]=eq.iloc[0]-1
    years=(r.end-r.start).days/365.25
    return {'cagr':float(eq.iloc[-1]**(1/years)-1),'cumulative':float(eq.iloc[-1]-1),'max_drawdown':float((path/path.cummax()-1).min()),'volatility':float(ret.std()*np.sqrt(252)),'avg_cash':float(r.weights.cash.mean()),'trade_days':len(r.trades),'trades_per_year':len(r.trades)/years,'stop_exits':int((r.trades.reason=='stop').sum()) if len(r.trades) else 0}

if __name__=='__main__':
    import argparse
    a=argparse.ArgumentParser();a.add_argument('--data',type=Path,default=Path(__file__).parent/'data');a.add_argument('--stop',type=float,default=.08);a.add_argument('--vol-target',type=float,default=.15);a.add_argument('--out',type=Path,default=Path('result'));args=a.parse_args()
    data=load_data(args.data);res=simulate(data,Config(stop=args.stop if args.stop>0 else None,vol_target=args.vol_target));args.out.mkdir(exist_ok=True,parents=True)
    res.equity.to_csv(args.out/'equity.csv');res.trades.to_csv(args.out/'trades.csv',index=False);res.weights.to_csv(args.out/'weights.csv');res.events.to_csv(args.out/'events.csv',index=False);print(json.dumps(metrics(res),ensure_ascii=False,indent=2))
