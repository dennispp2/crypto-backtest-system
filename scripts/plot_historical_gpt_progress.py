"""Read-only chart snapshot: matched realized history, never extrapolated AI.

Does not import a strategy runner, make inference calls, or alter any ledger.
History timestamps are bar OPEN labels; plot valuations at the following 4H
boundary. Source bytes are retained for reproducibility while the run advances.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def history(path):
    """Reject a partial concurrent CSV write instead of repairing/filling it."""
    for _ in range(5):
        raw = path.read_bytes()
        try:
            frame = pd.read_csv(io.BytesIO(raw), usecols=['timestamp', 'portfolio_value'])
            frame['timestamp'] = pd.to_datetime(frame.timestamp, utc=True, errors='raise')
            frame['portfolio_value'] = pd.to_numeric(frame.portfolio_value, errors='raise')
            valid = (len(frame) > 1 and not frame.isna().any().any()
                     and np.isfinite(frame.portfolio_value).all()
                     and frame.portfolio_value.gt(0).all()
                     and frame.timestamp.is_monotonic_increasing
                     and not frame.timestamp.duplicated().any()
                     and frame.timestamp.diff().dropna().ge(pd.Timedelta(hours=4)).all()
                     and frame.timestamp.diff().dropna().dt.total_seconds().mod(14400).eq(0).all())
            if valid and path.read_bytes() == raw:
                return frame, raw
        except (ValueError, pd.errors.ParserError):
            continue
    raise ValueError('SOURCE_HISTORY_NOT_STABLE_OR_COMPLETE')


def setup():
    chinese = Path('C:/Windows/Fonts/msjh.ttc')
    if not chinese.is_file():
        raise ValueError('CHINESE_FONT_UNAVAILABLE')
    font_manager.fontManager.addfont(str(chinese))
    plt.rcParams.update({
        'font.family': font_manager.FontProperties(fname=str(chinese)).get_name(),
        'font.size': 13, 'axes.unicode_minus': False, 'text.parse_math': False,
        'figure.facecolor': '#10151d', 'axes.facecolor': '#10151d',
        'text.color': '#edf1f7', 'axes.labelcolor': '#c7d0df',
        'xtick.color': '#aebbd0', 'ytick.color': '#aebbd0',
        'axes.edgecolor': '#445064', 'grid.color': '#293442',
        'savefig.facecolor': '#10151d', 'svg.fonttype': 'path',
    })


def decorate(ax):
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=.7, linewidth=.8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f'${value:,.0f}'))
    ax.set_ylabel('總資產 / USD', labelpad=14)
    ax.tick_params(axis='both', labelsize=12, pad=8)
    ax.margins(x=.01, y=.18)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = Path(args.run).resolve()
    if run.parent != (ROOT/'artifacts/ai_shadow_local/historical_v310_gpt_limited_v2').resolve():
        raise ValueError('UNEXPECTED_RUN_DIRECTORY')
    receipt_raw = (run/'run_receipt.json').read_bytes()
    receipt = json.loads(receipt_raw)
    contract_raw = (run/'experiment_contract.json').read_bytes()
    contract = json.loads(contract_raw)
    ai_name = 'combined_history_4h.csv' if receipt.get('full_period_completed') else 'progress_history_4h.csv'
    ai, ai_raw = history(run/ai_name)
    pure, pure_raw = history(run/'v310_comparator_history_4h.csv')
    matched = ai.merge(pure, on='timestamp', how='left', validate='one_to_one', suffixes=('_ai', '_v310'))
    if matched.isna().any().any() or len(matched) != len(ai):
        raise ValueError('MATCHED_PERIOD_COMPARISON_FAILED')
    start = pd.Timestamp(contract['start'])
    if matched.iloc[0].timestamp != start or pure.iloc[0].timestamp != start:
        raise ValueError('INITIAL_DATE_MISMATCH')
    initial = float(contract['initial_capital'])
    # The initial-capital point precedes the first bar-close mark and contribution.
    display = matched.set_index('timestamp').reindex(pd.date_range(start, matched.iloc[-1].timestamp, freq='4h'))
    full_display = pure.set_index('timestamp').reindex(pd.date_range(start, pure.iloc[-1].timestamp, freq='4h'))
    # Reindex inserts NaNs at missing bars so the renderer breaks the line.
    # Never forward-fill or interpolate a missing portfolio valuation.
    x = pd.DatetimeIndex([start, *(display.index+pd.Timedelta(hours=4))])
    ai_values = np.r_[initial, display.portfolio_value_ai.to_numpy()]
    pure_values = np.r_[initial, display.portfolio_value_v310.to_numpy()]
    full_x = pd.DatetimeIndex([start, *(full_display.index+pd.Timedelta(hours=4))])
    full_values = np.r_[initial, full_display.portfolio_value.to_numpy()]
    missing_bars = int(full_display.portfolio_value.isna().sum())
    stop = x[-1]
    output = run/'chart_snapshots'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in ((ai_name, ai_raw), ('v310_comparator_history_4h.csv', pure_raw),
                      ('run_receipt_snapshot.json', receipt_raw), ('experiment_contract.json', contract_raw)):
        (output/name).write_bytes(raw)
    (output/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    matched.assign(valuation_time=matched.timestamp+pd.Timedelta(hours=4)).to_csv(
        output/'matched_portfolio_values.csv', index=False)
    setup()
    fig, axes = plt.subplots(2, 1, figsize=(14, 10.8), gridspec_kw={'height_ratios': [1.05, 1]})
    fig.subplots_adjust(left=.105, right=.965, bottom=.19, top=.85, hspace=.49)
    fig.text(.105, .958, '總資產成長｜AI＋V3.10 vs 純 V3.10', fontsize=23, weight='bold')
    fig.text(.105, .917, f'初始 US${initial:,.0f}・每 4 小時追加 US$2・BTC / ETH / 現金',
             fontsize=14, color='#aebbd0')
    ax = axes[0]
    ax.plot(x, pure_values, color='#7ca7ff', linewidth=2.2,
            label=f'純 V3.10　${pure_values[-1]:,.2f}')
    ax.plot(x, ai_values, color='#f7b64b', linewidth=2.2,
            label=f'AI＋V3.10　${ai_values[-1]:,.2f}')
    ax.scatter(x[-1], pure_values[-1], color='#7ca7ff', marker='s', s=48, zorder=5)
    ax.scatter(x[-1], ai_values[-1], color='#f7b64b', marker='o', s=48, zorder=5)
    ax.set_title(f'同期間比較：2020/01/01 → {stop:%Y/%m/%d %H:%M} UTC',
                 loc='left', fontsize=16, pad=18)
    step_days = max(1, math.ceil((stop-start).total_seconds()/86400/5))
    tick_dates = list(pd.date_range(start, stop, freq=f'{step_days}D'))
    if tick_dates[-1] != stop:
        if len(tick_dates) > 1 and stop-tick_dates[-1] < pd.Timedelta(days=step_days/2):
            tick_dates.pop()
        tick_dates.append(stop)
    ax.set_xticks(tick_dates)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d\n%H:%M', tz=timezone.utc))
    ax.legend(loc='upper left', ncol=2, frameon=False, labelcolor='linecolor', fontsize=12)
    decorate(ax)
    ax = axes[1]
    ax.plot(full_x, full_values, color='#7ca7ff', linewidth=2.2,
            label=f'純 V3.10 最後總資產　${full_values[-1]:,.2f}')
    ax.set_title('純 V3.10 完整歷史曲線｜2020/01/01–2026/09/03（不含 AI）',
                 loc='left', fontsize=16, pad=18)
    ticks = [start, *[pd.Timestamp(f'{year}-01-01', tz='UTC') for year in range(2021, 2027)], full_x[-1]]
    ax.set_xticks(ticks)
    ax.set_xticklabels(['2020/01', *[str(year) for year in range(2021, 2027)], '2026/09'])
    ax.legend(loc='upper left', frameon=False, labelcolor='linecolor', fontsize=12)
    decorate(ax)
    ax.set_xlabel('日期（UTC；4H 收盤估值）', labelpad=12)
    unfinished = 'AI 回測尚未完成全期；上圖僅呈現已完成估值，未推估任何後續資產。' if not receipt.get('full_period_completed') else '上圖為完整已完成回測期間。'
    fig.text(.105, .073, unfinished, fontsize=12.5, color='#f7b64b')
    fig.text(.105, .043, '總資產含追加投入，不是純報酬率。探索版無法排除模型預訓練中的未來資訊。',
             fontsize=11.5, color='#aebbd0')
    if missing_bars:
        fig.text(.105, .015, f'原始全期歷史有 {missing_bars} 筆 4H 資料缺口；圖上保留空缺，未補值。',
                 fontsize=10.5, color='#aebbd0')
    fig.savefig(output/'portfolio_growth.png', dpi=180)
    fig.savefig(output/'portfolio_growth.svg')
    plt.close(fig)
    audit = {
        'chart': str(output/'portfolio_growth.png'), 'displayed_ai_valuation_end': stop.isoformat(),
        'matched_4h_rows': len(matched), 'ai_ending_value_displayed': float(ai_values[-1]),
        'pure_v310_same_date_value': float(pure_values[-1]),
        'pure_v310_full_period_ending_value': float(full_values[-1]),
        'source_run_full_period_completed': bool(receipt.get('full_period_completed')),
        'valuation_timestamp_contract': 'SOURCE_BAR_OPEN_PLUS_4_HOURS',
        'no_future_ai_projection': True, 'source_csv_matching': 'PASS',
        'full_period_missing_4h_bars': missing_bars, 'missing_values_interpolated': False,
        'source_sha256': {ai_name: hashlib.sha256(ai_raw).hexdigest(),
                          'v310_comparator_history_4h.csv': hashlib.sha256(pure_raw).hexdigest()},
    }
    (output/'chart_receipt.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
