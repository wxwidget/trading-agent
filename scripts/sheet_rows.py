"""Build typed, append-only ledger rows. Connector performs the verified write."""
import json,datetime,hashlib
from pathlib import Path
HEADERS={
 '月度计划':['运行ID','持仓月份','信号日','数据截止','研究截止','策略版本','沪深300权重','创业板权重','红利权重','黄金权重','恒生权重','现金权重','预测波动21日','预测波动126日','记录状态','调仓判断','宏观判断','中观判断','微观判断','冲突与风险','计划执行日','来源链接','输入指纹'],
 '持仓明细':['运行ID','持仓月份','信号日','资产代码','资产名称','目标权重','参考收盘价','综合动量','高于10月均线','信号资格','操作性质'],
 '研究依据':['运行ID','研究层级','来源名称','原文发布日期','核验时间','原文链接','核验事实','判断与局限'],
 '运行日志':['事件ID','运行ID','时间','阶段','结果','说明','输入指纹'],
 '使用说明':['项目','内容']}

def publication_state(run_id,plan_ids,logs):
 count=sum(value==run_id for value in plan_ids)
 commits=sum(len(row)>3 and row[1]==run_id and row[3]=='APPEND_COMMIT' for row in logs)
 if count>1 or commits>1:raise ValueError('duplicate live keys; manual investigation, no overwrite')
 if bool(count)!=bool(commits):raise ValueError('partial live publication; do not blindly retry')
 return bool(count and commits)

def build(plan,review):
 if review.get('corporate_actions_verified') is not True:raise ValueError('corporate actions not verified; append failure log only')
 if not review.get('execution_date') or review.get('signal_month_end_verified') is not True:raise ValueError('exchange calendar not verified')
 if review.get('status') not in ('READY','PARTIAL_REVIEW'):raise ValueError('invalid review status')
 if not review.get('sources'):raise ValueError('missing current research sources')
 known=datetime.datetime.fromisoformat(review['review_asof'])
 if not known.tzinfo:raise ValueError('research cutoff must include timezone')
 for source in review['sources']:
  pub=datetime.datetime.fromisoformat(source['published_at']) if source.get('published_at') else None
  checked=datetime.datetime.fromisoformat(source['verified_at'])
  if (pub is not None and (not pub.tzinfo or pub>known)) or not checked.tzinfo or checked>known:raise ValueError('future or timezone-free research source')
  if pub is None and '未知' not in source['limitation']:raise ValueError('unknown publication time must be disclosed')
 assets=plan['assets'];w={a['code']:a['weight'] for a in assets}
 if abs(sum(w.values())-1)>1e-7 or min(w.values())<-1e-7:raise ValueError('invalid allocation')
 key=plan['run_id'];month=plan['holding_month'];date=plan['signal_date']
 fingerprint=hashlib.sha256(json.dumps(plan['input_sha256'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
 links=review.get('spreadsheet_url','')
 rows={'月度计划':[[key,month,date,plan['data_asof'],review['review_asof'],plan['strategy'],
   *[w[c] for c in ('510300','159915','510880','518880','159920','CASH')],
   plan['forecast_vol']['21'],plan['forecast_vol']['126'],review['status'],plan['rebalance'],
   review['macro'],review['meso'],review['micro'],review['risks'],review['execution_date'],links,fingerprint]],
  '持仓明细':[[key,month,date,a['code'],a['name'],a['weight'],a.get('close'),a.get('momentum'),
    a.get('above_MA10'),a.get('eligible'),'目标计划；非成交；实际调仓待持仓核对'] for a in assets],
  '研究依据':[[key,s['layer'],s['title'],s.get('published_at') or '发布时间未知；见核验时间',s['verified_at'],s['url'],s['fact'],s['limitation']] for s in review['sources']],
  '运行日志':[[key+'|COMMIT',key,review['review_asof'],'APPEND_COMMIT',review['status'],
       '已计算目标并追加；未下单；重复运行按运行ID跳过',fingerprint]]}
 for tab,values in rows.items():
  if any(len(v)!=len(HEADERS[tab]) for v in values):raise ValueError('schema width mismatch')
 return rows

def cells(values):
 result=[]
 for value in values:
  if value is None:result.append({});continue
  kind='boolValue' if isinstance(value,bool) else 'numberValue' if isinstance(value,(int,float)) else 'stringValue'
  result.append({'userEnteredValue':{kind:value}})
 return {'values':result}

def append_requests(rows,locations):
 """Locations from live metadata and bounded reads; never guess next row."""
 requests=[]
 for tab,values in rows.items():
  loc=locations[tab];start=loc['next_row_index'];sid=loc['sheet_id'];width=len(HEADERS[tab]);end=start+len(values)
  if start<1 or end>loc['row_count']:raise ValueError('invalid/unallocated append tail')
  if start>1:
   requests.append({'copyPaste':{'source':{'sheetId':sid,'startRowIndex':start-1,'endRowIndex':start,'startColumnIndex':0,'endColumnIndex':width},
     'destination':{'sheetId':sid,'startRowIndex':start,'endRowIndex':end,'startColumnIndex':0,'endColumnIndex':width},'pasteType':'PASTE_FORMAT','pasteOrientation':'NORMAL'}})
  requests.append({'updateCells':{'range':{'sheetId':sid,'startRowIndex':start,'endRowIndex':end,'startColumnIndex':0,'endColumnIndex':width},
      'rows':[cells(v) for v in values],'fields':'userEnteredValue'}})
 return requests

if __name__=='__main__':
 import argparse
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--review',type=Path,required=True)
 a.add_argument('--out',type=Path,required=True);args=a.parse_args()
 args.out.write_text(json.dumps(build(json.loads(args.plan.read_text()),json.loads(args.review.read_text())),ensure_ascii=False,indent=2))
