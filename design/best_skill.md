# best_skill card

best_skill: time-series portfolio simulation with point-in-time signals, dual cash ledgers, benchmark horse-race, sensitivity and held-out cycle validation

train_signal: determine whether the frozen full crypto strategy has edge over equal-contribution fixed DCA without selecting rules on full-sample performance

selection_split: Primary three-asset backtest, Initial Capital Test 2, primary costs, overweight-only tactical sell order; compare Strategy D with Benchmark A and report every requested metric

heldout_gate: Initial Capital Test 1; low/high trading costs; cash protection off; technical-weakness sell ordering; literal overlapping cycle windows; BTC-only 2013+ threshold-event study; prefix-invariance no-look-ahead tests

accepted_patterns: completed UTC daily candles become available at the next UTC midnight; execution uses the next 4H open; all strategies receive the same external US$2 per 4H contribution; tactical and normal cash remain separate; parameters are read from the frozen JSON

rejected_patterns: backfilling BNB before listing; using same-day close for execution; choosing sensitivity winners as the primary rule; letting normal DCA consume tactical cash; comparing strategies with different contribution schedules; treating current Binance order filters as verified historical filters

patch_scope: one frozen strategy implementation and its reproducible data, QA, result and reporting bundle

reject_if: any signal timestamp is not strictly earlier than its execution bar; any ledger becomes materially negative; strategies in one capital test receive unequal contributions; raw hashes or source coverage are missing; prefix reruns change already-observed trades; a requested primary artifact is absent

