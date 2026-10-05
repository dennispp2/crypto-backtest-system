"""Verified first-month comparison; no inference, extrapolation or ledger writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def prepare(run, output):
    receipt = json.loads((run/'run_receipt.json').read_text(encoding='utf-8'))
    if receipt['status'] != 'COMPLETED_EXPLORATORY_MONTH' or not receipt['test_window_completed']:
        raise ValueError('MONTH_NOT_COMPLETE_NO_FINAL_CHART')
    if not receipt['live_and_frozen_files_unchanged'] or receipt['frozen_integrity'] != 'PASS':
        raise ValueError('MONTH_INTEGRITY_FAIL')
    contract = json.loads((run/'experiment_contract.json').read_text(encoding='utf-8'))
    metrics = json.loads((run/'period_metrics.json').read_text(encoding='utf-8'))
    frames = {name:pd.read_csv(run/file) for name,file in (
        ('純 V3.10','v310_comparator_history_4h.csv'),('V3.10＋AI','combined_history_4h.csv'))}
    timestamps = [pd.to_datetime(d.timestamp,utc=True) for d in frames.values()]
    if not timestamps[0].equals(timestamps[1]) or len(timestamps[0]) != 180:
        raise ValueError('MONTH_PAIRED_DATES_FAIL')
    if not timestamps[0].diff().dropna().eq(pd.Timedelta(hours=4)).all():
        raise ValueError('MONTH_CHART_TIME_GAP')
    start = pd.Timestamp(contract['start_4h_open'])
    x = pd.DatetimeIndex([start,*(timestamps[0]+pd.Timedelta(hours=4))])
    rows = []
    for name,frame in frames.items():
        values = np.r_[contract['initial_value'],frame.portfolio_value.astype(float)]
        if not np.isfinite(values).all() or not (values>0).all():
            raise ValueError('MONTH_CHART_VALUES_INVALID')
        for t,value in zip(x,values,strict=True):
            rows.append({'時間 UTC':t.strftime('%m/%d %H:%M'),'策略':name,'總資產 USD':float(value)})
    generated = datetime.now(timezone.utc).isoformat()
    caveats = ['GPT 可能記得歷史未來事件，因此不是經認證的無未來資訊測試。',
               '新聞、ETF、鏈上、衍生品及 VIX 缺漏，不以模型記憶補值。',
               '只有 30 天，不能據此判斷長期有效；未年化績效。']
    source = {'label':'首月獨立回測帳本',
              'files':[{'label':n} for n in ('v310_comparator_history_4h.csv','combined_history_4h.csv',
                                           'daily_ai_decisions.csv','period_metrics.json')],
              'filters':['幣種：BTC / ETH / USD 現金','資金：承接原前瞻起始部位','追加：US$2 / 4H'],
              'metricDefinitions':[{'name':'總資產', 'definition':'總資產是 BTC、ETH 的 4H 收盤市值與全部現金之和，包含外部追加本金。'}],
              'caveats':caveats,
              'evidenceFlow':[{'kind':'validation','title':'同起點比較',
                              'detail':'無 AI 干預重播與原前瞻帳本 181 個估值點一致；兩組均追加 US$360。'},
                             {'kind':'validation','title':'檔案保留',
                              'detail':'凍結程式校驗及原資產帳本前後雜湊一致。'}]}
    chart = {'schemaVersion':1,'id':'first-month-assets','queryId':'month-paired-history',
             'title':'首月總資產｜純 V3.10 與 V3.10＋AI',
             'description':'2026/09/03–10/03 UTC · gpt-5.6-sol · 歷史探索測試',
             'chart':{'type':'line','x':'時間 UTC','y':'總資產 USD','series':'策略','yLabel':'總資產 / USD',
                      'xLabel':'估值時間 / UTC','showXAxisLabel':True},
             'rows':rows,'source':source,'generatedAt':generated,'height':420,'theme':'codex-classic'}
    sources = {'schemaVersion':1,'items':[{'id':'first-month-assets','title':'首月總資產比較',
                'queries':[{'id':'month-paired-history','source':source,'rows':rows,
                            'columns':['時間 UTC','策略','總資產 USD'],
                            'reportingPeriod':'2026-09-03 08:00 至 2026-10-03 08:00 UTC',
                            'capturedAt':generated}]}]}
    output.mkdir(parents=True,exist_ok=False)
    for name,payload in (('reviewed-chart.json',chart),('reviewed-sources.json',sources)):
        (output/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(rows).to_csv(output/'paired_asset_values.csv',index=False)
    input_files = ('run_receipt.json','experiment_contract.json','period_metrics.json',
                   'v310_comparator_history_4h.csv','combined_history_4h.csv')
    digests = {name:hashlib.sha256((run/name).read_bytes()).hexdigest() for name in input_files}
    (output/'source_hashes.json').write_text(json.dumps(digests,indent=2),encoding='utf-8')
    static_plot(output,x,frames,metrics,contract)
    return output


def static_plot(output,x,frames,metrics,contract):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import font_manager
    from matplotlib.ticker import FuncFormatter
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    font = Path('C:/Windows/Fonts/msjh.ttc')
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(font)).get_name(),
                         'font.size':12,'axes.unicode_minus':False,'text.parse_math':False})
    fig,ax = plt.subplots(figsize=(12,7))
    fig.subplots_adjust(top=.79,bottom=.25,left=.11,right=.95)
    fig.text(.11,.94,'首月資產比較｜純 V3.10 vs V3.10＋AI',fontsize=20,weight='bold')
    fig.text(.11,.89,'2026/09/03–10/03 UTC · gpt-5.6-sol · 承接前瞻起始部位 · US$2 / 4H',color='#56616f')
    styles = [('純 V3.10','#3970c3','--','pure_v310'),('V3.10＋AI','#cd770e','-','v310_plus_ai')]
    for name,color,style,key in styles:
        values = np.r_[contract['initial_value'],frames[name].portfolio_value.astype(float)]
        ax.plot(x,values,label=f"{name}　${values[-1]:,.2f}",color=color,linestyle=style,lw=2.3)
        ax.scatter(x[-1],values[-1],color=color,s=35)
    invested = np.r_[contract['initial_value'],contract['initial_value']+frames['純 V3.10'].external_flow.cumsum()]
    ax.plot(x,invested,color='#8c929b',linestyle=':',lw=1.5,label=f'累計投入本金　${invested[-1]:,.0f}')
    ax.set_ylabel('總資產 / USD')
    ax.set_xlabel('估值日期 / UTC')
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_:f'${v:,.0f}'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.grid(axis='y',alpha=.25)
    ax.spines[['top','right']].set_visible(False)
    ax.legend(loc='upper left',frameon=False)
    q,ai = metrics['pure_v310'],metrics['v310_plus_ai']
    fig.text(.11,.115,f"TWR：純 V3.10 {q['twr_return']:+.2%} ｜ AI＋V3.10 {ai['twr_return']:+.2%}    "
                         f"Max DD：{q['max_drawdown']:.2%} / {ai['max_drawdown']:.2%}",fontsize=12)
    fig.text(.11,.065,'歷史探索測試：未使用當日之後的資料；GPT 歷史記憶風險未排除。\n'
                       '僅 30 天，不代表長期有效；回測未修改原前瞻帳本與凍結交易規則。',fontsize=10,color='#56616f')
    fig.savefig(output/'first-month-assets.png',dpi=220)
    fig.savefig(output/'first-month-assets.svg')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    args = parser.parse_args()
    run = Path(args.run).resolve()
    if run.parent != (ROOT/'artifacts/ai_shadow_local/v310_gpt_first_month').resolve():
        raise ValueError('MONTH_CHART_PATH_UNSAFE')
    output = run/'chart_snapshots'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    print(prepare(run,output))


if __name__ == '__main__':
    main()
