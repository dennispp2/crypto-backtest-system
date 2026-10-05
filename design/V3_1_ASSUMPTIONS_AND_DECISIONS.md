# V3.1 frozen assumptions and operational decisions

Frozen at `2026-09-03T08:13:49Z`, before the first V3.1 formal run. These decisions resolve wording that is not numerically complete; they are not selected from audit-period performance.

## Point-in-time contract

- A daily candle dated `t` is usable only at `t + 1 day 00:00 UTC`; a decision executes at the first common BTC/ETH 4-hour open at or after that availability time.
- The formal account starts fresh at exactly `2020-01-01 00:00 UTC`. Earlier BTC daily data supplies indicators and annual AI training only.
- The primary BTC daily series uses Bitstamp BTCUSD before Binance BTCUSDT exists and Binance thereafter, matching the existing project's documented source switch. AI and FSM use the same completed-daily series.
- The AI's label endpoint is the 60th future completed close. A training row is eligible for prediction year `Y` only when that endpoint is no later than `Y-1-12-31 23:59:59 UTC`.
- On each 4-hour bar, a newly available daily decision executes before that bar's invariant Fixed DCA. End-of-bar holdings are marked at that bar's close.
- The unchanged V3 normal-cash convention is retained: the USD 2 contribution is committed on every observed common 4-hour bar (including the first formal bar). While the crypto sleeves are within two percentage points of target, the commitment is split 62.5/37.5; outside that tolerance it is assigned to the most-underweight sleeve. Per-asset pending amounts execute when they reach the exchange minimum. Models B and C replay Model A's resulting DCA rows exactly.

## Qualitative rule definitions

- `SMA10 slope down/up` and `SMA20 slope down/up` compare today's value with three completed daily candles earlier. The separately stated SMA50 and SMA200 slopes use 10 and 20 days.
- Distribution condition C means close below the Bollinger middle band with either an intraday touch/rejection of the middle band or a preceding completed close also below it.
- EARLY_BEAR `failed reclaim` means the current and preceding completed closes both remain below SMA20 while the current close is below SMA50.
- `confirmed lower-high + lower-low` compares the latest completed 10-day high/low range with the immediately preceding non-overlapping 10-day range.
- `previous major low` is the lowest completed daily low in the prior 60 days, excluding the current day. Its break requires three consecutive structural-path days because Stage 4 otherwise has no stated confirmation count.
- The Stage-3 long-cycle clause is applied on each of its two confirmation days: at least two of five conditions plus close below SMA200 or non-rising SMA200.
- A macro cycle peak is the maximum completed BTC close from the 90 days through the Stage-1 signal and any later completed close in the same cycle. Bear-acceleration drawdown is measured from that point-in-time peak.
- Crash Level 1 remains active for ten completed trading days after activation. Level 2 uses the trailing 10-day peak-to-close drawdown as the operational meaning of `7-10 day`. A crash path rearms after five consecutive non-crash completed days.

## Cash ownership and unwind

- Cash from Stage 1 and either Crash Brake level is `temporary_hedge_cash`. Cash from Stage 2/3/4 and drift sells is `tactical_bear_cash`. These balances are never pooled in the accounting ledger.
- If EARLY_BEAR confirms, all then-existing temporary hedge cash is reclassified (without a market transaction) as tactical bear cash for that macro cycle.
- A temporary hedge lot becomes unwind-eligible after 20 completed trading days without EARLY_BEAR and five consecutive completed BULL-condition days. It is then repurchased over five daily executions, using only that lot's remaining cash. If BULL confirmation arrives later, the lot remains auditable; survival beyond 30 days without a bear confirmation is a design failure, not silently forgiven.
- Normal cash is used only by the existing Fixed DCA schedule. Tactical purchases may use their matching bear or temporary ledger only.

## FSM and execution semantics

- At most one ordinary FSM transition is allowed per completed daily signal. A state entered on today's signal cannot use the same signal to advance again; this prevents confirmation reuse across Stage 1/2/3/4. NEW_BULL may execute its first scheduled redeployment tranche when its seven-gate confirmation executes.
- The legal interpretation of the ambiguous printed chain `ACCUMULATION -> BEAR -> DEEP_BEAR or -> NEW_BULL` is `ACCUMULATION -> BEAR`, `ACCUMULATION -> DEEP_BEAR`, or `ACCUMULATION -> NEW_BULL`.
- A DEEP_BEAR structural exit to BEAR requires three consecutive days without the structural/acceleration condition. It does not itself buy; buyback can occur only through ACCUMULATION rules.
- AHR999 at or below 0.35 moves BEAR/DEEP_BEAR to ACCUMULATION with a 35% active target. Lower AHR values do not create further layers.
- Right-side targets are sequential: 35-to-50 first, then 50-to-60 on a later completed signal. Every executed buyback starts a seven-calendar-day accumulation lock.
- The confirmed-lower-low lock release is the lower-low condition plus close below SMA50 plus down-sloping SMA20 for three consecutive completed days. Crash Level 2 also releases the lock.
- NEW_BULL is entered only from ACCUMULATION after all seven gates. Bear cash is redeployed in ten daily tranches as `remaining cash / remaining days`, subject to the global 5-percentage-point and notional guards. It then becomes BULL and starts a 30-completed-trading-day ordinary-macro cooldown; Crash Brake remains allowed.
- An aborted distribution creates no confirmed macro cycle. Its Stage-1 cash stays temporary and follows the five-day unwind rule.
- All tactical state/target, crash, unwind, drift and buyback orders require an exposure gap of at least 5 percentage points and gross cash/notional of at least `max(100 USD, 1% of portfolio value)`. Failed orders remain deferred and are logged.
- The 20% hard floor is checked immediately after tactical sells only. Subsequent market movement may take exposure lower; it never forces a buy.

## AI semantics

- Model C uses exactly the seven named features and `XGBClassifier` with the frozen hyperparameters and seed 42. No validation split, tuning, calibration, early stopping, or model comparison is performed.
- An AI year is disabled if there are fewer than 500 eligible feature-complete matured rows, fewer than one positive class, or fewer than one negative class. The FSM then behaves exactly as Model B for that year.
- `AI_STAGE4_ACCELERATION` is recorded only when risk at least 0.70 actually causes a BEAR-to-DEEP_BEAR transition earlier than the FSM structural/acceleration path.
- `AI_BUYBACK_CAP` is recorded on a signal day only when risk at least 0.70 blocks an otherwise eligible 50% or 60% target. It is not counted merely because risk is high.
- OOS classification metrics use only formal-period rows with an actually generated annual-model prediction and a matured true label. Rows with disabled AI or immature labels are excluded and counted.

## Frozen promotion gates

The request specifies Model C gates but not numerical Model B gates. To prevent an after-the-fact subjective promotion, the following conservative Model-B gate is frozen now:

- all execution, DCA, cash, FSM and no-look-ahead hard audits pass;
- Max Drawdown improves by at least 10.0 percentage points versus Model A;
- Calmar is strictly greater than Model A;
- TWR CAGR is no more than 5.0 percentage points below Model A;
- no calendar year has more than three confirmed macro cycles (five or more remains a hard sensitivity failure);
- zero temporary hedge lots survive more than 30 calendar days without EARLY_BEAR confirmation;
- V3.1 tactical turnover is at least 10% below the frozen prior V3-E20 tactical-turnover benchmark `11.47886651675855`, hence at most `10.330979865082695`.

Model C uses the user's exact gates: at least 3.0 percentage points Max-DD improvement versus B, higher Calmar, no more than 2.0 percentage points CAGR loss, and no more than 10% tactical-turnover increase.

Final mapping is frozen: invalid hard audit -> `D`; valid B failure -> `A`; B pass and C failure -> `B`; B and C pass -> `C`.
