# V3.6 frozen assumptions and decisions

## Scope

V3.6 answers only whether a small buy-frequency guard can reduce the repeated bottom trading of the frozen V3.1 FSM-only Model B without materially weakening its bear protection. It does not redesign the macro regime model.

## Facts retained from V3.1

- BTC/ETH, 62.5%/37.5%, US$20,000 initial capital, 30% initial cash and US$2 per completed 4-hour interval.
- All V3.1 macro states, transitions, stage targets, AHR threshold, right-side confirmations, NEW_BULL logic, Crash L1/L2, costs, minimum notional and 20% tactical sell floor.
- Signals use a completed daily candle and execute no earlier than the next tradable 4-hour open.

## Decisions needed to make the prose executable

1. Model B is replayed by the untouched V3.1 engine. Model H follows the new DCA-first instruction. This ordering difference is explicitly reported and is not hidden as patch alpha.
2. A new 20-day-low field is permitted only as the requested buy rearm/cooldown guard. It cannot create a macro state, risk sell, crash sell or exposure target.
3. A new low is `close[t] <= min(close[t-20:t-1])`; the three-close stability gate uses only completed closes through `t`.
4. An accumulation episode starts at the first original V3.1 BEAR/DEEP_BEAR to ACCUMULATION transition, survives short ACCUMULATION/BEAR/DEEP_BEAR switches, and ends at NEW_BULL confirmation (or the macro cycle's formal completion).
5. V3.1 has no distinct `AHR_DEEP_VALUE_BUY`. V3.6 reserves the audit label but does not invent a new action.
6. A tactical sell while an accumulation episode is active starts the seven-calendar-day re-buy cooldown, including legal V3.1 crash or bearish-rebreak sells.
7. A genuinely eligible Crash L1/L2 sell vetoes a same-timestamp accumulation buy. The sell itself remains unchanged and executes through the original V3.1 crash processor.
8. RIGHT_SIDE_TO50 is restricted to 35%->50%, and RIGHT_SIDE_TO60 to 50%->60%, as stated by the V3.6 instruction. Their original market predicates and targets remain unchanged.
9. Whipsaw pairs are adjacent bottom-scope tactical events with opposite sides no more than seven calendar days apart. BTC and ETH rows sharing one tactical event ID count once.
10. Audit windows and promotion thresholds are reporting-only. They do not appear in the trading engine.

## Known interpretation risk

The phrase "no new indicators" conflicts literally with the required 20-day-low rearm condition. The implementation treats it as a point-in-time administrative buy guard, not a market-regime indicator. The historical path is still one retrospectively chosen crypto sample, so a passing result supports paper testing only, not live deployment.
