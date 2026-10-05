# V3.2 assumptions and decisions — frozen before formal run

## Scope

- V3.2 is a bounded challenger built from the already-frozen V3.1 FSM-only Model B.
- V3.1 source rules and outputs remain the reference; Model B is rerun with the original V3.1 engine.
- No AI, BNB, dynamic DCA, parameter search, or performance-aware trading logic is allowed.

## Resolved ambiguities

- The drawdown promotion gate is `maximum_drawdown >= -0.30`, matching the user's corrected mathematical definition.
- Promotion gates are evaluated only after all trades are complete and are not imported by the engine module.
- `Material Tactical Cash Time lower than V3.1` means strict numerical reduction; no extra effect-size threshold is imposed.
- A crypto `trading day` is one completed UTC daily candle because BTC/ETH trade continuously.
- Bull Recovery uses the existing `ACCUMULATION` FSM state plus an explicit `recovery_mode` flag; no eighth state is invented.
- The 30-day NEW_BULL cooldown starts on confirmation. Five redeploy days occur inside that window; the remaining cooldown persists after return to BULL.
- One ordinary FSM transition is allowed per completed daily signal. Crash Brake remains an independent overlay and may execute at the same next 4H bar.
- `Crash Level 2 Active` includes a Level-2 condition confirmed on the current completed daily signal while Level 1 is active.
- The 2023–2025 exposure answer is reported both for actual BULL/NEW_BULL state observations and for the fixed calendar window.
- “Significant” churn reduction is diagnostic only and is frozen as at least 50% fewer BEAR-to-DEEP_BEAR plus DEEP_BEAR-to-BEAR transitions than V3.1 B. It is not an added promotion gate.

## Bias and comparability controls

- H0 receives no external cash after inception, so absolute ending wealth is not directly comparable to A/B/D. The normalized TWR chart is the fair investment-performance comparison.
- V3.2 reuses the frozen V3.1 raw inputs so B row integrity can be exact rather than being confounded by a later market-data cutoff.
- The final 2025–2026 event window may be incomplete at the data cutoff and is labeled accordingly.
- Historical success does not establish future robustness; the promotion decision is only eligibility for forward paper testing.

