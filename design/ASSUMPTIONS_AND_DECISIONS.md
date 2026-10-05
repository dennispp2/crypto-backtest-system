# Frozen interpretation decisions

## Confirmed facts from the supplied specification

- Signals are calculated from completed UTC daily candles and may execute no earlier than the next 4-hour open.
- Primary crypto weights are BTC 50%, ETH 30%, and BNB 20%.
- Normal cash and tactical cash are separate ledgers.
- External capital must be equal across strategies.
- Tactical exposure is capped at 60%, leaving at least a 40% core position.
- The fixed AHR999 formula uses coefficients 5.84 and -17.01. Only BTC receives AHR999.

## Data facts verified before implementation

- Binance Spot's first returned 4H BTCUSDT and ETHUSDT bars after the requested start are 2017-08-17 04:00 UTC.
- Binance Spot's first returned 4H BNBUSDT bar is 2017-11-06 00:00 UTC. A three-asset portfolio therefore cannot be honestly initialized on 2017-08-01.
- The current Binance Spot NOTIONAL filter is USDT 5 for BTCUSDT, ETHUSDT, and BNBUSDT. This is a current snapshot, not proof of every historical filter.

## Modeling choices required because the specification is incomplete or internally ambiguous

1. **Common start.** The primary backtest starts at the first common completed 4H timestamp for all three assets, expected to be 2017-11-06 00:00 UTC. The requested 2017-08-01 date is retained in the data contract as unavailable for a three-asset initialization; no synthetic BNB history is created.
2. **Equal contributions.** Every strategy receives an external contribution of US$2 at every 4H bar. The strategy decides whether to spend US$1-US$3 from accumulated normal cash. This is the only interpretation that simultaneously makes contributions equal and gives cash protection economic meaning.
3. **Initial trades.** Initial crypto purchases execute at the first common 4H open and incur the same fee and slippage assumptions as later trades.
4. **Minimum order.** A frozen US$5 quote-notional floor is used for all assets because point-in-time historical Binance filters are unavailable. Amounts below the floor accumulate in per-asset pending normal-DCA ledgers. This is a modeled constraint and is reported as a limitation.
5. **Within-band DCA allocation.** If all crypto weights are within two percentage points of target, new DCA follows 50/30/20. Otherwise all new DCA is assigned to the most underweight asset; materially overweight assets receive zero.
6. **Severe overheat.** Before a sell stage, the frozen Primary Overheat Gate itself is the operational definition of "severe overheat" and reduces dynamic DCA to US$1.5.
7. **Stage progression.** At most one sell stage can be added per completed daily candle. Stage 2 requires Stage 1 to have existed before that candle, and likewise for later stages. This prevents a single close from retroactively satisfying four confirmations.
8. **Intermediate deterioration.** Stage 4 defines it point-in-time as `SMA20 down AND SMA20 < SMA50 AND Close < SMA50` on the signal day.
9. **Tactical exposure target.** At a stage execution, tactical cash is raised toward 15/30/45/60% of the current tactical sleeve (`crypto market value + tactical cash`). Transaction costs may leave a small shortfall.
10. **Buyback tranche base.** "Full Crypto Portfolio" is operationalized at each trigger as the current tactical sleeve value (`crypto market value + tactical cash`) immediately before the buy. The 5/25/20/10% tranches therefore mirror the maximum 60% sell exposure and are always capped by actual tactical cash, so the strategy never borrows or buys back more than it sold.
11. **Right-side ordering and cycle reset.** "Finally reserve up to 10%" is interpreted as a sequence constraint: right-side confirmation is eligible only after at least one AHR999 undervaluation buyback tranche has executed in an earlier completed daily signal. A right-side-confirmation purchase is the terminal event of that sell-state cycle and resets the Sell Stage even if price declines have caused residual tactical cash to exceed the 10% purchase cap. Residual money remains labeled Tactical Cash and may still be used only by a later permitted AHR999/right-side buyback. The cycle also resets whenever all tactical cash has otherwise been redeployed. No price pivot or future cycle boundary is used.
12. **Benchmark C.** Dynamic-DCA-only computes the same point-in-time hypothetical sell stage for DCA-speed control but executes no tactical sell or buyback.
13. **Annual rebalance.** Benchmark B rebalances the crypto sleeve at the first 4H open of each UTC calendar year, using sells before buys and paying costs.
14. **Cycle windows.** The requested windows are used literally and may overlap (2019-2020 overlaps 2020-2022; 2022-2024 overlaps 2024-2026). They are descriptive slices, not independent statistical samples.
15. **AHR999 event study.** A threshold event is the first daily downward crossing into a threshold episode. Forward returns use the trigger close and future daily closes. Later forward prices are outcomes, never trading inputs.
16. **Expanding fit.** The alternative fitted-value regression uses only observations strictly before the signal day and requires at least 730 prior daily observations.
17. **Risk metrics.** Risk-free rate is zero. Time-weighted returns remove external flows at each 4H bar; annualization uses 365.25 days and six 4H bars per day.

These decisions are frozen before the primary result is inspected. Sensitivity outputs are descriptive and cannot replace the primary rules.
