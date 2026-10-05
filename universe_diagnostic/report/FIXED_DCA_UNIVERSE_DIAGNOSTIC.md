# Fixed DCA Universe Diagnostic

## Outcome

**C. FIXED DCA RESULT STRONGLY BNB-DEPENDENT**

This is an isolated diagnostic. It did not execute or alter the V3 Macro FSM,
regime labels, hedge stages, floors, or buybacks. The complete machine audit is
**PASS**, and the mandatory U3 row-integrity
reproduction is **PASS**.

## 2020 fresh-start results

| Universe | Final USD | XIRR | TWR CAGR | Max DD | Sharpe | Sortino | Calmar |
| --- | --- | --- | --- | --- | --- | --- | --- |
| U1 | $234,082.59 | 34.27% | 36.96% | -74.48% | 0.8524 | 0.8444 | 0.4962 |
| U2 | $276,646.83 | 38.19% | 42.32% | -76.87% | 0.8838 | 0.8573 | 0.5506 |
| U3 | $419,364.04 | 48.26% | 52.29% | -74.30% | 0.9923 | 0.9481 | 0.7038 |

All runs used the same USD 20,000 initial portfolio, USD 6,000 initial cash,
70% initial crypto allocation, USD 2 per elapsed 4H interval, and identical V2
primary execution costs.

### 2020 pairwise deltas (left minus right)

| Comparison | Delta final USD | Delta CAGR pp | Delta Max DD pp | Delta Calmar |
| --- | --- | --- | --- | --- |
| U3 vs U1 | $185,281.45 | 15.3321 | 0.1805 | 0.2076 |
| U3 vs U2 | $142,717.22 | 9.9657 | 2.5725 | 0.1532 |
| U2 vs U1 | $42,564.23 | 5.3665 | -2.3920 | 0.0544 |

A positive Delta Max DD means the left universe had a shallower drawdown because
drawdowns are stored as negative values.

## Direct answers

1. **Removing BNB:** U2 ended **$142,717.22 below U3**,
   equal to **34.03% of U3's ending value**.
2. **BNB contribution to U3 profit:** BNB's accounting net-profit contribution
   was **$186,286.53**, or
   **50.33%** of total U3 portfolio profit.
3. **BTC-only lower Max DD:** **No**. U1 Max DD was
   -74.48% versus U3
   -74.30%.
4. **BTC+ETH better risk-adjusted return:** Relative to U3, **no**: 2020-start
   Calmar was 0.5506 vs 0.7038,
   and Sharpe was 0.8838 vs 0.9923.
   Relative to BTC-only, U2 did have higher Calmar (0.5506
   vs 0.4962) despite a deeper Max DD.
5. **How BNB-driven was the Champion:** U3's BNB sleeve supplied
   50.33% of U3 total profit,
   while the opportunity-cost test shows a 34.03%
   ending-value loss when BNB is replaced by proportionally more BTC/ETH.
6. **Robust if BNB cannot repeat:** The cross-universe Fixed DCA outcome is not
   automatically invalid, but the original U3 Champion return should not be
   treated as robust to a weaker future BNB path. Rolling-start evidence below
   determines whether the advantage persisted beyond the 2020 low-base entry.

## Rolling fresh-start ending values

| Start year | U1 | U2 | U3 |
| --- | --- | --- | --- |
| 2020 | $234,082.59 | $276,646.83 | $419,364.04 |
| 2021 | $88,058.39 | $89,751.90 | $134,701.55 |
| 2022 | $66,735.86 | $54,811.98 | $56,765.70 |
| 2023 | $94,935.79 | $76,626.54 | $76,284.43 |

U3-vs-U2 ending-value uplift by start: 2020: 51.59%, 2021: 50.08%, 2022: 3.56%, 2023: -0.45%. The advantage was large for
both 2020 and 2021 fresh starts, almost disappeared for 2022, and turned slightly
negative for 2023. It is therefore not accurate to attribute the entire effect
only to a 2020 entry. The absolute 2020 uplift was
14.47 times the median
absolute uplift from the 2021/2022/2023 fresh starts.

## Interpretation limits

- BNB accounting profit share and U3-minus-U2 opportunity-cost uplift answer
  different questions; both are reported.
- Results are historical and depend on the frozen Binance-derived price path,
  survivorship of the selected assets, stablecoin/USD equivalence, and the
  simplified fixed fee/slippage model.
- This is not evidence that Fixed DCA beats lump sum, cash, or other schedules;
  those controls were intentionally outside scope.
- The verdict gates and allocations were frozen before results. No allocation
  or V3 hedge parameter was changed after observing them.

## Audit summary

- U3 final-value delta versus V2 Champion: 0.000000000000 USD.
- U3 trade rows: 4,889; numeric max absolute delta:
  1.46e-11.
- U3 daily rows: 2,437; numeric max absolute delta:
  5.82e-11.
- Forbidden action rows: 0; sell rows: 0.
- Recorded signal rows: 0.
- Fresh initial-allocation violations: 0.
- External-contribution spread within each start: 0.000000000000 USD.
