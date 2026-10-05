# V3.10 Forward Paper Test — Execution Contract

## Task mode

Deterministic forward paper validation.  This is not model selection, parameter
search, retraining, or live trading.

## Frozen boundary

- Champion: V3.10 Model Q.
- Comparator: V3.1 Model B.
- Historical cutoff: `2026-09-03T04:00:00+00:00`.
- OOS rows must have a 4-hour open strictly later than the cutoff and a close
  strictly earlier than the Binance server time used for that collection.
- The original V3.10, V3.1, V3.9 source and frozen data files are read-only.
- A single historical replay is allowed only to capture and verify the exact
  cutoff state. Later runs restart from that frozen state and replay only the
  append-only OOS prefix.

## Data contract

- Primary source: Binance Spot public klines, BTCUSDT and ETHUSDT.
- New downloads are immutable timestamped batches under
  `v3_10_forward/data/raw`.
- Signals use completed UTC daily candles and execute at the first tradable 4H
  open at or after signal availability.
- No future-return label enters the execution frame.
- Duplicate, revised, missing, incomplete, or non-contiguous common 4H rows
  fail closed.

## Validation split and gates

- Selection period: none. The strategy is already frozen.
- Held-out period: every completed common 4H bar strictly after the cutoff.
- Minimum checkpoint: 180 calendar days and 3 resolved new Stage3 candidates.
- Early safety failures: frozen-code drift, look-ahead, incomplete candles,
  execution exception, or blocked unchanged V3.1 Stage4/Crash action.
- Until the checkpoint is mature, the only valid verdict is
  `INSUFFICIENT_EVIDENCE` (unless an early safety failure occurs).

## Append-only guarantees

Every ledger row contains a deterministic `record_id`, `prev_record_hash`, and
`record_hash`. Existing prefixes are verified byte-semantically before new rows
are appended. Corrections are new `EXECUTION_EXCEPTION` records; historical
records are never overwritten.

