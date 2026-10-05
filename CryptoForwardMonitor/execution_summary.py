"""Read-only presentation of committed paper ledgers; never infer fills from signals."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


LEDGERS = {
    "tactical": ("forward_trade_log_v310.csv", {
        "record_id", "execution_timestamp", "side", "reason", "btc_notional_usd",
        "eth_notional_usd", "fee_usd", "slippage_usd",
    }),
    "dca": ("forward_fixed_dca_log.csv", {
        "record_id", "timestamp", "external_flow", "executed_dca", "pending_dca_cash",
    }),
}
REASONS = {
    "TEN_DAY_NEW_BULL_REDEPLOY": "新牛市確認後，依凍結規則分十天恢復加密貨幣部位。",
}


@dataclass(frozen=True)
class LedgerSnapshot:
    rows: dict[str, list[dict[str, str]]]
    errors: tuple[str, ...] = ()


def amount(value: str) -> Decimal:
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise ValueError("金額不是有效的非負數")
    return number


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("時間缺少時區")
    return result


def local_time(value: str) -> str:
    return timestamp(value).astimezone().strftime("%Y-%m-%d %H:%M %z")


def read_ledgers(directory: Path) -> LedgerSnapshot:
    data: dict[str, list[dict[str, str]]] = {}
    errors = []
    for kind, (name, required) in LEDGERS.items():
        try:
            with (directory / name).open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError("缺少必要欄位")
                rows = list(reader)
            ids = set()
            for row in rows:
                if not row["record_id"] or row["record_id"] in ids:
                    raise ValueError("紀錄識別碼空白或重複")
                ids.add(row["record_id"])
                timestamp(row["execution_timestamp" if kind == "tactical" else "timestamp"])
                fields = ("btc_notional_usd", "eth_notional_usd", "fee_usd", "slippage_usd") if kind == "tactical" else ("external_flow", "executed_dca", "pending_dca_cash")
                for field in fields:
                    amount(row[field])
                if kind == "tactical" and row["side"] not in {"BUY", "SELL"}:
                    raise ValueError("未知買賣方向")
            data[kind] = rows
        except (OSError, UnicodeError, csv.Error, ValueError, InvalidOperation, TypeError) as exc:
            data[kind] = []
            errors.append(f"{name}：無法驗證帳本（{exc}）")
    return LedgerSnapshot(data, tuple(errors))


def appended_rows(before: LedgerSnapshot, after: LedgerSnapshot) -> LedgerSnapshot:
    errors = [*before.errors, *after.errors]
    delta = {}
    for kind in LEDGERS:
        old, new = before.rows[kind], after.rows[kind]
        if new[:len(old)] != old:
            errors.append(f"{kind}：既有帳本被改寫或縮短，不能確認本次新增交易。")
        delta[kind] = new[len(old):]
    return LedgerSnapshot(delta, tuple(dict.fromkeys(errors)))


def render_summary(snapshot: LedgerSnapshot, *, heading: str, context: str) -> str:
    lines = [heading, "", context, "", "僅紙上模擬，沒有向交易所下單。時間為帳本執行時間（本機時區），不是按鈕點擊時間。",
             "範圍：V3.10 戰術成交，以及 Fixed DCA 對照模型 A 的定投帳本。",
             "定投資料不是 V3.10／V3.1 的逐筆成交證明；V3.1 戰術成交明細目前未輸出。", ""]
    if snapshot.errors:
        return "\n".join([*lines, "【資料不足，不能判定有無成交】", *snapshot.errors])
    tactical, dca = snapshot.rows["tactical"], snapshot.rows["dca"]
    buys = sum(amount(r["btc_notional_usd"]) + amount(r["eth_notional_usd"]) for r in tactical if r["side"] == "BUY")
    sells = sum(amount(r["btc_notional_usd"]) + amount(r["eth_notional_usd"]) for r in tactical if r["side"] == "SELL")
    invested = sum(amount(r["external_flow"]) for r in dca)
    executed = sum(amount(r["executed_dca"]) for r in dca)
    lines += ["【重點摘要】", f"戰術買入 ${buys:,.2f}｜戰術賣出 ${sells:,.2f}（名目金額）",
              f"對照模型 A：定投入金 ${invested:,.2f}｜定投實際執行 ${executed:,.2f}（帳本口徑）", "",
              "【V3.10 戰術買賣明細】"]
    if not tactical:
        lines.append("此範圍沒有新增戰術成交。這不代表沒有定投或沒有模型訊號。")
    for row in sorted(tactical, key=lambda r: timestamp(r["execution_timestamp"])):
        side = "買入" if row["side"] == "BUY" else "賣出"
        lines.append(f"\n{local_time(row['execution_timestamp'])}｜{side}")
        for asset in ("BTC", "ETH"):
            notional = amount(row[f"{asset.lower()}_notional_usd"])
            if notional:
                lines.append(f"  {asset}：${notional:,.2f}；成交幣數：原始帳本未提供")
        lines += [f"  原因：{REASONS.get(row['reason'], '尚無白話對照，請參照原始原因代碼。')}",
                  f"  原因代碼：{row['reason']}",
                  f"  手續費 ${amount(row['fee_usd']):,.4f}｜滑價成本 ${amount(row['slippage_usd']):,.4f}"]
        if row.get("signal_timestamp"):
            lines.append(f"  訊號時間（原始值）：{row['signal_timestamp']}")
    lines += ["", "【Fixed DCA 對照模型 A 明細】", "固定定投帳本不提供每筆幣種成交拆分、成交幣數或成交價；以下金額不應按配置比例當成實際成交拆分。"]
    if not dca:
        lines.append("此範圍沒有新增定投帳本紀錄。")
    for row in sorted(dca, key=lambda r: timestamp(r["timestamp"])):
        value = amount(row["executed_dca"])
        action = f"定投買入合計 ${value:,.2f}" if value else "本筆未成交，資金留待定投執行"
        lines.append(f"{local_time(row['timestamp'])}｜入金 ${amount(row['external_flow']):,.2f}｜{action}｜待投現金 ${amount(row['pending_dca_cash']):,.2f}")
    lines += ["原因：執行固定定投排程；入金不等於立即成交，成交以 executed_dca 為準。", "",
              "【來源】", *[name for name, _ in LEDGERS.values()],
              "不以行情反推成交幣數，也不將訊號、配置目標或掛單當作成交。"]
    return "\n".join(lines)


def latest_ledger_summary(directory: Path) -> str:
    snapshot = read_ledgers(directory)
    dates = [timestamp(r["execution_timestamp" if kind == "tactical" else "timestamp"]).astimezone().date()
             for kind, rows in snapshot.rows.items() for r in rows]
    latest = max(dates) if dates else None
    selected = {kind: [r for r in rows if timestamp(r["execution_timestamp" if kind == "tactical" else "timestamp"]).astimezone().date() == latest]
                for kind, rows in snapshot.rows.items()}
    return render_summary(LedgerSnapshot(selected, snapshot.errors), heading="最近帳本日｜紙上交易摘要",
                          context=f"帳本日期：{latest or '無資料'}。此為既有帳本回顧，不是本次執行的新增交易；尚未保存新版執行摘要。")
