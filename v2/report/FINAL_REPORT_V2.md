# V2.0 Fixed DCA + Corrected Cycle Hedge — Final Report

## Scope and validity

- Formal period: 2020-01-01T00:00:00+00:00 to 2026-09-02T08:00:00+00:00.
- Fresh initial portfolio: US$20,000 at formal-period start; 2019 is indicator warm-up only.
- Primary costs: 0.10% fee + 0.05% slippage; US$5 modeled minimum notional.
- Frozen models only: A, E20, E30, E40. No optimization or parameter search.
- No-look-ahead and execution audit: **PASS**.
- Fixed-DCA A/E20 row integrity: **PASS**.

## Headline performance

| strategy | final_portfolio_value | external_contributions | xirr | time_weighted_cagr | maximum_drawdown | calmar | average_crypto_exposure | time_in_tactical_cash | transaction_count | total_fees |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A - Fixed DCA Champion | US$419,364.04 | US$49,238.00 | 48.26% | 52.29% | -74.30% | 0.704 | 95.12% | 0.00% | 4889 | US$43.19 |
| E20 - Fixed DCA + Corrected Hedge | US$361,100.20 | US$49,238.00 | 44.58% | 48.86% | -74.04% | 0.660 | 80.72% | 97.87% | 5420 | US$3,491.32 |
| E30 - Fixed DCA + Corrected Hedge | US$373,955.98 | US$49,238.00 | 45.44% | 49.72% | -73.41% | 0.677 | 81.27% | 97.87% | 5421 | US$3,497.30 |
| E40 - Fixed DCA + Corrected Hedge | US$396,996.71 | US$49,238.00 | 46.91% | 51.20% | -72.68% | 0.704 | 82.41% | 97.87% | 5417 | US$3,474.55 |

## Required answers

1. **2020–2026 Fixed DCA final value:** US$419,364.04.
2. **E20 final value:** US$361,100.20.
3. **Did E20 reduce maximum drawdown?** Yes; A -74.30%, E20 -74.04%, improvement 0.25 percentage points.
4. **E20 maximum-drawdown cycle:** no active cycle (post-reset BULL gap after cycle 10, before cycle 11); regime at trough `BULL`, trough 2022-06-18T16:00:00+00:00. The hedge had already reset before the deepest 2022 decline.
5. **2021/5 Stage 3 with 90%+ crypto exposure:** 0 daily observations; PASS. However, 2021-05-11 through 2021-05-31 was Stage 0, regime BULL, with crypto exposure 94.15%–96.99%; the corrected label did not create an active May-crash hedge.
6. **Every confirmed NEW_BULL reset its stage:** PASS; missing resets = 0.
7. **Stage 4 stuck for 1–3 years:** maximum Stage-4-to-reset/end span 60.0 days; not observed.
8. **Was tactical cash still idle for long periods?** Longest continuous positive tactical-cash run = 2101 days; time positive = 97.87%. This is a factual duration, not proof that every day was avoidable drag.
9. **Best frozen floor by Calmar:** E40 - Fixed DCA + Corrected Hedge at 0.7044. This comparison does not promote or retune the floor.
10. **Is Fixed DCA still the best absolute-return model?** Yes; highest final value = A - Fixed DCA Champion at US$419,364.04.
11. **Is the hedge worth live trading?** Historical simulation label: **INSUFFICIENT HEDGE EDGE**. A forward test is still required before live use because cycle count is small and execution/tax effects outside the frozen model remain untested.
12. **J Law verdict:** shown below.

## E20 versus A

- Delta final value: US$-58,263.84.
- Delta TWR CAGR: -3.43 percentage points.
- Delta maximum drawdown: 0.25 percentage points.
- Delta Calmar: -0.044.
- CAGR sacrificed per 1 percentage-point drawdown improvement: 13.512 percentage points.

## J Law decision

- Champion: A — Fixed DCA.
- Challenger: E20 — Fixed DCA + Corrected Cycle Hedge, 20% sell-time floor.
- Return Edge: Champion.
- Drawdown Edge: Challenger.
- Cash Drag: 61.10% total-cash path attribution; 24.86% tactical-only path attribution. These are descriptive approximations.
- Cycle Timing: 19 machine-defined sell cycles; maximum Stage-4 span 60.0 days. The maximum drawdown occurred in the post-cycle-10 BULL gap before cycle 11, showing a timing miss rather than a stuck-stage bug.
- Execution Integrity: PASS.
- Overfit Risk: Medium-high — thresholds were frozen and only 20/30/40 floors were compared, but 19 machine cycles are not 19 independent macro cycles, and the rule tree remains complex.

**FINAL VERDICT: HEDGE NEEDS REDESIGN**

## Important interpretation boundary

The hard floor is enforced against tactical sells. Daily mark-to-market exposure can later fall below the floor when crypto prices fall relative to cash; forcing an immediate buy would add a new, unfrozen rebalancing rule. Such observations remain visible in `exposure_audit.csv` and are not silently relabeled as execution bugs.
