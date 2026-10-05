# V3.10 analysis route

- Selected skill: `Full-empirical-analysis-skill` (Python).
- Why: V3.10 is a freeze-first, reproducible, multi-model empirical backtest with a narrow treatment, baseline/reference replay gates, sensitivity analysis, machine-readable audits, figures, and a fixed verdict rule.
- Applied parts: explicit data contract; frozen design before the formal run; H0/A/B/P39/Q controls; causal-lineage and scope audits; rolling fresh starts; no-look-ahead prefix invariance; manifests, hashes, tests, and report QA.
- Deliberate adaptation: regression assumptions, coefficient tables, and causal estimands are not applicable to a deterministic portfolio simulation. The requested replay checks, event windows, candidate counterfactual diagnostics, and rolling-start sensitivity replace them. Rolling starts overlap heavily and are not treated as independent statistical samples.
