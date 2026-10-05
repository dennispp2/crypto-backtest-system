# Analysis log

## Accepted patterns

- Point-in-time daily availability and next-4H-open execution passed prefix invariance.
- Equal US$2/4H contributions passed across all primary benchmarks.
- Normal DCA and tactical cash ledgers remained isolated.
- Primary rules remained frozen; the full 54-cell sensitivity grid was reported without promotion.

## Rejected patterns

- 2017-08-01 three-asset initialization: rejected because BNBUSDT was unavailable.
- Historical exchange-filter precision: rejected as unsupported; current US$5 filter is labeled a model proxy.
- Selecting the best sensitivity cell: rejected by design.

## Final live-readiness gate

`FINAL_SIMPLIFIED_STRATEGY.md` produced: False
