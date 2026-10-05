# V3.5 Patch D — frozen assumptions and decisions

Patch D was supplied after V3.4 FINAL had already been frozen and formally started. Because it changes AHR999, right-side buyback, and bearish rebreak behavior that V3.4 explicitly prohibited changing, the only audit-safe implementation is a new V3.5 / Model G. V3.4 outputs remain immutable evidence.

- V3.4 A/B/C patches and V3.3 state hysteresis remain unchanged. Patch D is the only new trading scope.
- AHR999 value-base buying is limited to DEEP_BEAR or an existing ACCUMULATION episode with a target below 35%. BEAR at the unchanged 55% target does not enter ACCUMULATION solely because AHR999 is low.
- A successful DEEP_BEAR 25-to-35 value-base action creates the episode. Short ACCUMULATION/DEEP_BEAR changes retain its id. A confirmed 35-to-25 hard failure marks an exit; a new id is created only after the full 14-day + new-20-day-low + three-no-new-low rearm sequence and a successful value-base re-entry.
- Normal hard-failure actions move exactly one rung. A 60-to-50 or 50-to-35 move remains ACCUMULATION; 35-to-25 enters DEEP_BEAR after execution. Crash L3 remains exempt.
- The 14-day cooldown begins at execution time of any non-crash Patch-D accumulation buy or sell. Signals inside the cooldown are logged and blocked.
- Macro Bull Requalification and original NEW_BULL validation take priority over Patch D on the same completed daily signal. Crash L3 remains the independent post-FSM emergency overlay.
- Whipsaw pairs use adjacent non-crash bottom tactical actions with opposite sides and no more than 14 calendar days between execution timestamps.
- The 2022 and 2026 windows are audit-only. All success gates are evaluated only after the frozen full run.
