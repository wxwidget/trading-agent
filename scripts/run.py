"""Refresh a frozen strategy and calculate a dated plan. Never places orders."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,json,hashlib,platform
import numpy as np,pandas as pd
import core,solver
ROOT=Path(__file__).resolve().parents[1]
VERSION='etf-momentum-solver-v1.0.0'
NAMES=dict(zip(core.CODES,['沪深300ETF','创业板ETF','红利ETF','黄金ETF','恒生ETF']))

def seed(folder):
 frames={k:pd.read_csv(Path(folder)/f'{k}.csv.gz',index_col=0,parse_dates=True).reindex(columns=core.CODES)
         for k in ('open','close','div','tradable','volume')}
 frames['tradable']=frames['tradable'].astype(bool)
 return frames

def qfq(code,start,cut):
 import requests
 parts=[]
 for year in range(start.year,cut.year+1):
  response=requests.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',params={
     'param':f'{code},day,{year}-01-01,{year}-12-31,640,qfq'},timeout=25)
  response.raise_for_status();data=response.json()['data'][code]
  rows=data.get('qfqday',data.get('day',[]))
  if not rows:raise ValueError(f'{code}: empty qfq year {year}')
  part=pd.DataFrame([v[:6] for v in rows],columns=['date','open','close','high','low','volume']).set_index('date').astype(float)
  part.index=pd.to_datetime(part.index);parts.append(part)
 return pd.concat(parts).loc[lambda x:~x.index.duplicated()].sort_index().loc[start:cut]

def refresh(frames,cut,fetcher=None,qfetch=None):
 if cut<=frames['close'].index[-1]:
  if cut not in frames['close'].index:raise ValueError('signal date missing in snapshot')
  return {k:v.loc[:cut].copy() for k,v in frames.items()},[]
 if fetcher is None:
  import akshare as ak
  fetcher=lambda c:ak.fund_etf_hist_sina(symbol=c).set_index('date')
 qfetch=qfetch or qfq
 last=frames['close'].index[-1]
 with ThreadPoolExecutor(max_workers=5) as pool:values=list(pool.map(fetcher,core.CODES))
 fresh={}
 for c,value in zip(core.CODES,values):
  raw=value.copy();raw.index=pd.to_datetime(raw.index);raw=raw.sort_index().loc[:cut]
  if raw.index.has_duplicates or cut not in raw.index:raise ValueError(f'{c}: missing/duplicate signal date')
  if (raw[['open','close','high','low']].loc[cut]<=0).any():raise ValueError(f'{c}: invalid signal price')
  if not np.isfinite(raw.volume.loc[cut]) or raw.volume.loc[cut]<=0:raise ValueError(f'{c}: invalid signal volume')
  overlap=frames['close'].index.intersection(raw.index)[-126:]
  valid=frames['tradable'].loc[overlap,c]
  for field in ('open','close'):
   if (frames[field].loc[overlap,c][valid]-raw.loc[overlap,field][valid]).abs().max()>.0021:
    raise ValueError(f'{c}: overlap mismatch or corporate action, manual review required')
  fresh[c]=raw
 dates=fresh['sh510300'].loc[last+pd.Timedelta(days=1):cut].index
 if len(dates)==0 or dates[-1]!=cut:raise ValueError('incomplete date index')
 additions={k:pd.DataFrame(index=dates,columns=core.CODES) for k in frames}
 audit=[]
 for c in core.CODES:
  raw=fresh[c];new=raw.reindex(dates)
  valid=new[['open','close']].notna().all(axis=1)&(new.volume>0)
  additions['open'][c]=new.open;additions['close'][c]=new.close
  additions['volume'][c]=new.volume;additions['tradable'][c]=valid
  dividends=pd.Series(0.,index=dates)
  if c.startswith('sh'):
   adj=qfetch(c,last,cut);common=adj.index.intersection(raw.index)
   if last not in common or not dates.isin(common).all():raise ValueError(f'{c}: qfq coverage incomplete')
   offset=(adj.loc[common,'close']-raw.loc[common,'close']).round(3)
   for field in ('open','high','low'):
    if ((adj.loc[common,field]-raw.loc[common,field])-offset).abs().max()>.0021:
     raise ValueError(f'{c}: non-additive adjustment/split')
   delta=offset.diff().round(3)
   if (delta<-.003).any():raise ValueError(f'{c}: negative adjustment, investigate')
   dividends=delta.reindex(dates).where(lambda s:s>.003,0.)
  else:
   # Original Shenzhen pool has no post-bootstrap distributions assumed.
   # Agent MUST verify dividend/split announcements before releasing the plan.
   audit.append({'code':c,'check':'VERIFY_NO_NEW_DIVIDEND_OR_SPLIT','since':str(last.date())})
  additions['div'][c]=dividends
  audit.append({'code':c,'new_rows':len(dates),'new_dividend_sum':float(dividends.sum()),'cut':str(cut.date())})
 output={k:pd.concat([frames[k],additions[k]]) for k in frames}
 output['close']=output['close'].astype(float).ffill()
 output['open']=output['open'].astype(float).fillna(output['close'].shift())
 output['div']=output['div'].astype(float);output['volume']=output['volume'].astype(float)
 output['tradable']=output['tradable'].astype(bool)
 if output['close'].isna().any().any():raise ValueError('unresolved prices')
 return output,audit

def data(frames):
 tr=((frames['close']+frames['div'])/frames['close'].shift()).fillna(1.).cumprod()
 if (tr.pct_change().abs()>.25).any().any():raise ValueError('large move/corporate action requires review')
 return core.Data(frames['open'],frames['close'],frames['div'],tr,frames['tradable'])

def calculate(d,cut):
 cfg=core.Config(stop=None,vol_target=.10,exclude_gold=False)
 w,status=solver.target(d,cut,cfg,'momentum_solver')
 ret=d.tr.loc[:cut].pct_change().dropna();vol={str(n):float(np.sqrt(max(0.,w@(ret.tail(n).cov().to_numpy()*252)@w))) for n in (21,126)}
 if w.min()<-1e-7 or w.sum()>1+1e-7 or max(vol.values())>.10+1e-7:raise ValueError('infeasible target')
 m=d.tr.loc[:cut].groupby(d.tr.loc[:cut].index.to_period('M')).last()
 mom={str(k):m.iloc[-1]/m.iloc[-k-1]-1 for k in (3,6,12)}
 score=sum(mom.values())/3;gate=(score>0)&(m.iloc[-1]>m.tail(10).mean())
 assets=[{'code':c[2:],'name':NAMES[c],'close':float(d.close.loc[cut,c]),'weight':float(v),
   'momentum':float(score[c]),'above_MA10':bool(m.iloc[-1][c]>m.tail(10).mean()[c]),
   'eligible':bool(gate[c]),**{f'mom{k}':float(s[c]) for k,s in mom.items()}} for c,v in zip(core.CODES,w)]
 assets.append({'code':'CASH','name':'现金/货币基金','weight':float(1-w.sum()),'close':None})
 return {'strategy':VERSION,'signal_date':str(cut.date()),'data_asof':str(cut.date()),
   'holding_month':str(cut.to_period('M')+1),'run_id':f'{VERSION}|{cut.date()}',
   'assets':assets,'forecast_vol':vol,'solver':status,'review_status':'PENDING',
   'rebalance':'待核对真实持仓与20日冷静期；5pp门槛；不是成交记录','tree_enabled':False}

def main():
 a=argparse.ArgumentParser();a.add_argument('--signal-date',required=True)
 a.add_argument('--out',type=Path,required=True);a.add_argument('--offline',action='store_true')
 a.add_argument('--corporate-actions',type=Path,help='Verified Shenzhen cash dividends JSON list: code,date,amount,source_url')
 args=a.parse_args();cut=pd.Timestamp(args.signal_date);args.out.mkdir(parents=True,exist_ok=True)
 try:
  frames=seed(ROOT/'assets/seed')
  if args.offline and cut>frames['close'].index[-1]:raise ValueError('offline snapshot stale: no current plan')
  frames,audit=refresh(frames,cut)
  if args.corporate_actions:
   for event in json.loads(args.corporate_actions.read_text()):
    code=event['code'];date=pd.Timestamp(event['date']);amount=float(event['amount'])
    if code not in ('sz159915','sz159920') or date>cut or date<=pd.Timestamp('2026-10-30') or amount<0 or not event.get('source_url'):
     raise ValueError('invalid or unverified corporate action')
    if date not in frames['div'].index:raise ValueError('corporate action date missing')
    frames['div'].loc[date,code]=amount
    audit.append({'verified_corporate_action':event})
  plan=calculate(data(frames),cut)
  plan['created_at']=pd.Timestamp.now(tz='Asia/Shanghai').isoformat();plan['runtime']={'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__}
  snapshot=args.out/'snapshot';snapshot.mkdir(exist_ok=True)
  for k,v in frames.items():v.to_csv(snapshot/f'{k}.csv.gz',compression='gzip')
  plan['input_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.glob('*.csv.gz')}
  (args.out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2,default=str))
  (args.out/'refresh_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
  pd.DataFrame(plan['assets']).to_csv(args.out/'targets.csv',index=False)
  print(json.dumps(plan,ensure_ascii=False,indent=2,default=str))
 except Exception as error:
  (args.out/'error.json').write_text(json.dumps({'status':'BLOCKED_DATA','signal_date':str(cut.date()),'reason':str(error)},ensure_ascii=False,indent=2))
  raise
if __name__=='__main__':main()
