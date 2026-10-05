from __future__ import annotations

import re

from market import MarketSnapshot
from parser import ForwardStatus


STATE_LABELS = {
    "BULL": "牛市",
    "LATE_BULL": "牛市後段",
    "DISTRIBUTION": "高檔風險升高期",
    "EARLY_BEAR": "熊市初期",
    "BEAR": "熊市",
    "DEEP_BEAR": "深度熊市",
    "ACCUMULATION": "低檔累積期",
    "NEW_BULL": "新牛市確認期",
}

ACTION_LABELS = {
    "NO_ACTION": "今天沒有新的紙上模型動作",
    "NEW_BULL_CONFIRMED": "牛市重新進入條件已全部成立，模型確認進入新牛市階段",
    "NEW_BULL_REDEPLOY": "模型已依凍結規則執行今天的分批恢復曝險",
    "STAGE3_ELIGIBILITY_ACTIVATED": "Stage3 觀察資格已啟用；這只是開始監控，目前不代表 Stage3 訊號成立",
    "STAGE3_REENTRY_CANDIDATE": "偵測到 Stage3 重新進場候選，仍需等待規則確認",
    "STAGE3_REENTRY_CONFIRMED": "Stage3 重新進場條件已確認",
    "STAGE3_HELD_FOR_3_CLOSE_CONFIRMATION": "Stage3 候選仍在等待三個收盤確認",
    "ABORTED_DISTRIBUTION": "高檔風險訊號已取消",
    "EARLY_BEAR_TO_DISTRIBUTION": "熊市初期訊號降回高檔風險觀察期",
    "DEEP_BEAR_TO_BEAR_NO_AUTO_BUY": "深度熊市狀態回到熊市，但沒有觸發自動買進",
    "ACCUMULATION_LOCK_RELEASE_LOWER_LOW": "市場再創低點，低檔累積鎖定已解除",
    "NEW_BULL_COMPLETE_COOLDOWN_30": "新牛市恢復曝險程序完成，進入 30 日冷卻期",
}

OUTCOME_LABELS = {
    "EXECUTED": "已執行",
    "SKIPPED": "未執行",
    "BLOCKED": "已阻擋",
    "BELOW_MIN_NOTIONAL": "低於最小交易金額，未執行",
}


def _money(value: float | None) -> str:
    return "無資料" if value is None else f"${value:,.2f}"


def _percent(value: float | None) -> str:
    return "無資料" if value is None else f"{value:.2f}%"


def _state_label(raw: str) -> str:
    return f"{STATE_LABELS.get(raw, '未定義狀態')}（{raw}）"


def _yes_no(raw: str) -> str:
    value = raw.strip().upper()
    if value == "YES":
        return "有（YES）"
    if value == "NO":
        return "無（NO）"
    return raw


def _stage_label(stage: int) -> str:
    if stage == 0:
        return "0（目前沒有啟動熊市減碼階段）"
    return f"{stage}（目前處於第 {stage} 階段風險控制）"


def _evaluation_label(status: ForwardStatus) -> str:
    if status.evaluation_eligible:
        return f"可以正式評估（原始值：{status.current_evaluation}）"
    if status.current_evaluation == "INSUFFICIENT_EVIDENCE":
        return "資料仍不足，暫時不能判定策略好壞（原始值：INSUFFICIENT_EVIDENCE）"
    return f"尚不可正式評估（原始值：{status.current_evaluation}）"


def _hash_label(raw: str) -> str:
    return "通過（PASS，凍結檔案未被改動）" if raw == "PASS" else f"警告（{raw}，需要檢查模型完整性）"


def _action_explanation(raw: str) -> str:
    base, separator, outcome = raw.partition(":")
    if match := re.fullmatch(r"STAGE([1-4])_SELL", base):
        explanation = f"第 {match.group(1)} 階段風險減碼事件"
    elif base.startswith("RIGHT_TO_"):
        explanation = f"右側確認後恢復曝險至 {base.removeprefix('RIGHT_TO_')}%"
    elif base == "AHR999_TO35":
        explanation = "AHR999 低估值回補至 35% 曝險"
    elif base == "DRIFT_SELL":
        explanation = "執行持倉漂移修正減碼"
    elif base == "CRASH_L1":
        explanation = "啟動第一級崩盤保護"
    elif base == "CRASH_L2":
        explanation = "啟動第二級崩盤保護"
    elif base.startswith("STAGE3_ELIGIBILITY_EXIT"):
        explanation = "Stage3 觀察資格已終止"
    else:
        explanation = ACTION_LABELS.get(base, "模型記錄了一項事件")
    if separator and outcome in OUTCOME_LABELS:
        explanation = f"{explanation}；結果：{OUTCOME_LABELS[outcome]}"
    return f"• {explanation}\n  原始紀錄：{raw}"


def _exposure_explanation(status: ForwardStatus) -> str:
    target = status.v310_target_exposure
    actual = status.v310_actual_exposure
    gap = status.v310_exposure_gap
    if target is None or actual is None or gap is None:
        return "目前沒有完整的曝險資料。"
    if gap > 0.01:
        return (
            f"紙上投資組合目前有 {actual:.2f}% 是加密貨幣，凍結模型的目標是 {target:.2f}%，"
            f"目前還相差 {gap:.2f} 個百分點。後續是否增加曝險，仍由凍結規則逐日判定，不需要手動補足。"
        )
    if gap < -0.01:
        return (
            f"紙上投資組合目前曝險為 {actual:.2f}%，高於 {target:.2f}% 目標約 {abs(gap):.2f} 個百分點；"
            "可能是市場價格變動造成，模型會依凍結規則處理。"
        )
    return f"紙上投資組合目前曝險 {actual:.2f}%，已接近 {target:.2f}% 的模型目標。"


def build_latest_report(status: ForwardStatus, market: MarketSnapshot | None) -> str:
    btc = market.btc.price if market else status.btc
    eth = market.eth.price if market else status.eth
    state_text = _state_label(status.v310_state)
    no_crash = status.crash.strip().upper() == "NO"
    no_candidate = status.stage3_candidate.strip().upper() == "NO"
    actions = [item.strip() for item in status.today_tactical_action.split("|") if item.strip()]
    if not actions:
        actions = ["NO_ACTION"]
    action_text = "\n\n".join(_action_explanation(action) for action in actions)
    risk_summary = (
        f"目前{'沒有' if no_crash else '有'}崩盤訊號，"
        f"也{'沒有' if no_candidate else '有'} Stage3 候選。"
    )
    drawdown = (
        "無資料" if status.current_drawdown is None
        else f"目前資產比前瞻測試高點低 {abs(status.current_drawdown):.2f}%"
    )
    progress_note = (
        "兩個門檻都已達成，可以開始正式評估。"
        if status.evaluation_eligible
        else "目前只是資料累積階段，不能用這些早期數字判定策略成功或失敗。"
    )

    return f"""最新報告｜白話版

【一句話重點】
模型目前判定為「{state_text}」。{risk_summary}

【目前部位代表什麼】
{_exposure_explanation(status)}

【今天模型做了什麼】
{action_text}

注意：以上是紙上模型紀錄，App 不會替你下單，也不是要求你手動照做。

【目前風險】
• 崩盤訊號：{_yes_no(status.crash)}
• Stage3 候選：{_yes_no(status.stage3_candidate)}
• 回撤：{drawdown}
• 模型檔案完整性：{_hash_label(status.frozen_hash_status)}

【前瞻測試進度】
• 已累積樣本外天數：{status.oos_elapsed or 0:g} / 180 天
• 已完成判定的 Stage3 候選：{status.resolved_candidates or 0} / 3 個
• 評估狀態：{_evaluation_label(status)}
• 說明：{progress_note}

【原始稽核資料】
• BTC 即時價格：{_money(btc)}
• ETH 即時價格：{_money(eth)}
• V3.10 狀態：{status.v310_state}
• V3.10 階段：{_stage_label(status.v310_stage)}
• 目標曝險：{_percent(status.v310_target_exposure)}
• 實際曝險：{_percent(status.v310_actual_exposure)}
• 曝險差距：{_percent(status.v310_exposure_gap)}
• Frozen Hash：{status.frozen_hash_status}
• Current Evaluation：{status.current_evaluation}
"""
