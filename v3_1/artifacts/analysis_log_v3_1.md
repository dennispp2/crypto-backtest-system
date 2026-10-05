# V3.1 analysis log

## Accepted
- Frozen two-asset 62.5/37.5 universe and exact Model-A DCA replay in B/C.
- Seven-state FSM, separate temporary/bear cash ownership, sell-time hard floor, and next-bar execution.
- Exactly seven XGBoost inputs and annual expanding-window training using matured labels only.

## Rejected
- BNB, dynamic DCA, date hard-coding, extra features/models, AI direct trading, parameter search, and post-result retuning.

## Scope
- This is a deterministic historical simulation plus annual OOS classifier diagnostics, not a causal estimate or future-return guarantee.
