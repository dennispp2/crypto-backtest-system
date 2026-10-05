# V2 analysis log

## Accepted patterns

- V1 Model A was called directly and its normal-DCA schedule was replayed exactly in every Model E run.
- Formal performance was reinitialized at 2020-01-01; 2019 was warm-up only.
- Daily signals executed no earlier than the next available 4H open.
- Sell stages, drift-band maintenance, one-shot buybacks, NEW_BULL deployment, and reset state are explicit and audited.
- Only the frozen E20/E30/E40 floor comparison was run.

## Rejected patterns

- Dynamic DCA, annual rebalancing, cash protection, V1 Full Strategy, automated optimization, and choosing a floor then rerunning rules were not used.
- An always-on daily hard-floor rebalance was rejected because it would add an unfrozen forced-buy rule. The hard floor constrains tactical sells; mark-to-market breaches are disclosed.

## Gates

- Audit pass: True
- Fixed-DCA mismatch rows: 0
- Prefix invariant: True
- Final verdict: HEDGE NEEDS REDESIGN
