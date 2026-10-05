# Crypto BTC+ETH Fixed DCA + Macro Hedge V3.1

## Final verdict

**B. V3.1 FSM PROMOTED TO FORWARD PAPER TEST**

- `FSM_EDGE = PASS`
- `AI_EDGE = FAIL`
- `FIXED_DCA_ROW_INTEGRITY = PASS`
- `NO_LOOK_AHEAD_AUDIT = PASS`

## Performance

| model | final_portfolio_value | twr_cagr | maximum_drawdown | calmar | tactical_turnover |
| --- | --- | --- | --- | --- | --- |
| A | US$279,201.22 | 42.50% | -76.87% | 0.5529 | 0.0000x |
| B | US$348,746.85 | 47.69% | -39.51% | 1.2070 | 9.3677x |
| C | US$354,423.82 | 48.55% | -38.39% | 1.2648 | 9.4223x |

## Direct answers

1. BTC+ETH Fixed DCA ended at **US$279,201.22**.
2. V3.1 FSM-only ended at **US$348,746.85**.
3. V3.1 FSM+AI ended at **US$354,423.82**.
4. Max DD A/B/C: **-76.87% / -39.51% / -38.39%**.
5. Calmar A/B/C: **0.5529 / 1.2070 / 1.2648**.
6. 2021/11-2022/06 Stage4: FSM **2021-05-24 00:00:00+00:00**; AI **2021-05-24 00:00:00+00:00**.
7. AI made Stage4 earlier: **NO**.
8. 2022/06 AI blocked an early 35-to-50/60 buyback **0 time(s)**; therefore **NO**.
9. 2021/05 case peak-to-trough DD A/B/C: **-44.94% / -33.20% / -33.28%**.
10. 2025-2026 case peak-to-trough DD A/B/C: **-58.00% / -28.24% / -21.77%**.
11. Confirmed macro cycles: **B=3, C=3**. Annual frequency is in `macro_cycle_frequency_v3_1.csv`.
12. **YES, tactical cash remains long-term.** It was material (>1% of portfolio) for **96.23% / 96.23%** of B/C observations, and ending tactical bear cash was **US$195,453.09 / US$198,228.73**. The narrower temporary-hedge test did pass: over-30-day unconfirmed lots **B=0, C=0**, with ending temporary cash zero.
13. Tactical turnover: **B=9.3677x, C=9.4223x**.
14. AI OOS ROC-AUC / PR-AUC / Brier: **0.6788 / 0.2868 / 0.1721**.
15. AI improved real portfolio performance under all frozen value gates: **NO**.
16. FSM is worth a forward paper test under the frozen gate: **YES**.
17. AI should be retained as a promoted challenger: **NO**.
18. J Law Final Verdict: **B. V3.1 FSM PROMOTED TO FORWARD PAPER TEST**.

## Frozen gate details

FSM checks:

```json
{
  "hard_audits_pass": true,
  "max_dd_improvement_ge_10pp": true,
  "calmar_above_a": true,
  "cagr_loss_le_5pp": true,
  "cycles_per_year_le_3": true,
  "temporary_unwind_fail_zero": true,
  "turnover_at_least_10pct_below_v3": true
}
```

AI checks:

```json
{
  "hard_audits_pass": true,
  "max_dd_improvement_ge_3pp": false,
  "calmar_above_b": true,
  "cagr_loss_le_2pp": true,
  "turnover_increase_le_10pct": true
}
```

## J Law verdict

| J Law field | Verdict evidence |
| --- | --- |
| Champion | MODEL B |
| Challenger | MODEL C |
| Return Edge | Final A/B/C: US$279,201.22 / US$348,746.85 / US$354,423.82 |
| Drawdown Edge | Max DD A/B/C: -76.87% / -39.51% / -38.39% |
| Calmar Edge | A/B/C: 0.553 / 1.207 / 1.265 |
| Cash Drag | HIGH: material cash B/C 96.23% / 96.23%; ending bear cash US$195,453.09 / US$198,228.73 |
| Bear Timing | Stage4 B=2021-05-24 00:00:00+00:00; C=2021-05-24 00:00:00+00:00; AI earlier=False |
| Bull Re-entry | Seven-gate NEW_BULL plus 10-day redeploy; see cycle and trade logs |
| Crash Protection | 2021/05 case DD A/B/C: -44.94% / -33.20% / -33.28% |
| Bottom Buyback Quality | 2022/06 AI cap interventions=0; see buyback_forward_10d_v3_1.csv |
| AI Edge | FAIL |
| Turnover | B=9.3677x; C=9.4223x |
| Execution Integrity | PASS |
| Overfit Risk | FSM remains one retrospectively designed historical rule path; AI probabilities are annual OOS but not a proof of future alpha |

## Interpretation limits

- The FSM is not a clean out-of-sample discovery: it is a frozen, human-designed rule set evaluated on one crypto history. Audit dates were not present in execution code, but knowledge of historical regimes can still influence design.
- AI predictions are genuinely annual expanding-window out-of-sample predictions. Portfolio value, however, is still only one realized path and classification skill does not imply trading value.
- Bitstamp BTCUSD supplies the pre-Binance history and Binance BTCUSDT supplies the later series. Source-switch and input hashes are in the data contract and manifest.
- AHR999 uses the pre-existing fixed arithmetic curve. It is point-in-time at execution but inherits the model-risk of that fixed curve.
- The formal FSM promotion gate passes, but B still held material tactical cash for 96.23% of observations and ended with US$195,453.09 in bear cash. `PROMOTED TO FORWARD PAPER TEST` is not approval for live capital; the high-cash behavior is a central forward-test risk.
- No threshold was changed after the run. Failed gates remain failed.
