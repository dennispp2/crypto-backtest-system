# V3.9 analysis route

- Selected skill: `Full-empirical-analysis-skill` (Python).
- Why: the task is a frozen-rule, reproducible, multi-model empirical backtest with integrity, sensitivity, audit-table, and reporting requirements.
- Applied parts: freeze-first design, explicit data contract, baseline/control/challenger comparison, rolling-start sensitivity, machine-readable outputs, figures, and integrity tests.
- Deliberate adaptation: regression-specific diagnostics and causal language are not applicable to a deterministic portfolio simulation. The requested H0/A/B/P comparisons, event windows, rolling starts, and no-look-ahead checks replace them.
