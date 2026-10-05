# Invalid preliminary attempt 1

- Invalidated at: 2026-09-03T13:58:32Z
- Status: INVALID; excluded from all formal V3.8 conclusions and promotion gates.
- Defect: AHR was incorrectly allowed on the third subsequent completed daily close. The frozen specification requires closes one, two and three to remain blocked, with eligibility beginning only at the first tradable bar after the third close.
- Correction: the cooldown boundary implementation and unit test were corrected before the valid formal rerun.
- Parameter changes: none. The frozen three-completed-close rule and every promotion threshold remained unchanged.
- Trace-only invalid K metrics: final value 338119.173013, TWR CAGR 0.46933488, maximum drawdown -0.39428848, Calmar 1.19033, tactical turnover 8.91237, tactical events 101.
