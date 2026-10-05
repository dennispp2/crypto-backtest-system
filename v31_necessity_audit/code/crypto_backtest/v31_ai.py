from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBClassifier


def annual_walk_forward_predictions(
    daily: pd.DataFrame,
    rules: dict[str, Any],
    formal_start: pd.Timestamp,
    formal_end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit once per calendar year using only labels matured by prior year-end."""
    ai = rules["ai"]
    features = list(ai["features"])
    work = daily.copy().sort_values("signal_date").reset_index(drop=True)
    work["prediction_available_at"] = pd.to_datetime(work["signal_available_at"], utc=True)
    mask = work["prediction_available_at"].between(formal_start, formal_end, inclusive="both")
    prediction_rows = work.loc[mask].copy()
    outputs: list[pd.DataFrame] = []
    training_audit: list[dict[str, Any]] = []

    for year, prediction_year in prediction_rows.groupby(prediction_rows["prediction_available_at"].dt.year, sort=True):
        cutoff = pd.Timestamp(year=int(year) - 1, month=12, day=31, hour=23, minute=59, second=59, tz="UTC")
        eligible = work.loc[
            work[features].notna().all(axis=1)
            & work["bear_label"].notna()
            & work["label_end_date"].notna()
            & (pd.to_datetime(work["label_end_date"], utc=True) <= cutoff)
        ].copy()
        positives = int(eligible["bear_label"].sum())
        negatives = int(len(eligible) - positives)
        enabled = bool(len(eligible) >= int(ai["minimum_matured_rows"]) and positives > 0 and negatives > 0)
        reason = "ENABLED" if enabled else (
            "INSUFFICIENT_MATURED_ROWS" if len(eligible) < int(ai["minimum_matured_rows"])
            else "SINGLE_CLASS_TRAINING_SET"
        )
        predicted = prediction_year.copy()
        predicted["training_cutoff"] = cutoff
        predicted["training_rows"] = int(len(eligible))
        predicted["training_positive_rows"] = positives
        predicted["training_negative_rows"] = negatives
        predicted["ai_enabled"] = enabled
        predicted["feature_complete"] = predicted[features].notna().all(axis=1)
        predicted["bear_risk"] = np.nan
        scale_pos_weight = float(negatives / positives) if positives else np.nan
        model_version = f"AI_DISABLED_{reason}_Y{year}"
        if enabled:
            params = dict(ai["hyperparameters"])
            params["scale_pos_weight"] = scale_pos_weight
            model = XGBClassifier(**params)
            model.fit(eligible[features].astype(float), eligible["bear_label"].astype(int))
            valid = predicted["feature_complete"]
            if valid.any():
                predicted.loc[valid, "bear_risk"] = model.predict_proba(
                    predicted.loc[valid, features].astype(float)
                )[:, 1]
            model_version = f"XGB_V3_1_Y{year}_N{len(eligible)}_P{positives}_SEED{params['random_state']}"
        predicted["model_version"] = model_version
        predicted["scale_pos_weight"] = scale_pos_weight
        outputs.append(predicted)
        training_audit.append(
            {
                "prediction_year": int(year),
                "training_cutoff": cutoff,
                "model_version": model_version,
                "ai_enabled": enabled,
                "disabled_reason": "" if enabled else reason,
                "training_rows": int(len(eligible)),
                "positive_rows": positives,
                "negative_rows": negatives,
                "scale_pos_weight": scale_pos_weight,
                "training_first_feature_date": eligible["signal_date"].min() if not eligible.empty else pd.NaT,
                "training_last_feature_date": eligible["signal_date"].max() if not eligible.empty else pd.NaT,
                "training_last_label_end_date": eligible["label_end_date"].max() if not eligible.empty else pd.NaT,
                "cutoff_violation_count": int((pd.to_datetime(eligible["label_end_date"], utc=True) > cutoff).sum()),
            }
        )
    if not outputs:
        raise RuntimeError("No formal-period AI prediction rows")
    predictions = pd.concat(outputs, ignore_index=True).sort_values("prediction_available_at").reset_index(drop=True)
    return predictions, pd.DataFrame(training_audit)
