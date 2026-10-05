# Fixed DCA Universe Diagnostic — frozen pre-analysis protocol

## Isolation

This diagnostic is a pure Fixed DCA experiment. It calls the existing V1/V2
Fixed DCA engine and reads only the frozen processed market panel plus V2
Champion outputs for the U3 reproduction gate. It does not import, call, or
write any Macro FSM, stage, floor, buyback, hedge, or V3 implementation.

The diagnostic may report evidence relevant to universe concentration. Its
results must not be used to alter V3 rules within this run.

## Fixed experiment

- Same 2020/2021/2022/2023 fresh starts and common V2 end.
- Same USD 20,000 initial capital, 70% initial crypto, 30% initial USD.
- Same USD 2 per elapsed 4H interval, V2 primary fee/slippage, and USD 5
  per-asset modeled minimum notional.
- U1: BTC 100%; U2: BTC 62.5% / ETH 37.5%; U3: BTC 50% / ETH 30% / BNB 20%.
- No strategy selection or allocation adjustment after observing results.

## Interpretation boundary

"Asset net-profit contribution" is ending marked asset value minus all cash
budgets spent buying that asset, including initial allocation. The percentage
of portfolio profit uses total portfolio net profit as denominator. "Removing
BNB impact" is U3 minus U2 and therefore measures the opportunity-cost effect
of replacing the 20% BNB target with proportionally more BTC and ETH; it is not
identical to BNB's standalone accounting profit.

This experiment compares Fixed DCA universes. It does not establish that DCA is
superior to lump-sum investing, holding cash, or any other deployment schedule.

## Frozen verdict gates

The machine verdict follows `config/frozen_universe_rules.json`. Strong BNB
dependence requires all three strong gates. Robustness requires all three robust
gates. Every other successfully audited outcome is classified as partial.

