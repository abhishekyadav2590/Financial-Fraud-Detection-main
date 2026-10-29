"""Compare recent saved inputs with the synthetic model-training reference."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from extensions import db
from model_schema import FEATURE_NAMES, NUMERICAL_FEATURES
from models import Transaction


REFERENCE_DATA_PATH = Path(__file__).resolve().parent.parent / "dataset" / "transactions.csv"
WINDOW_DAYS = 30
MIN_REFERENCE_SAMPLES = 100
MIN_RECENT_SAMPLES = 30
MAX_RECENT_SAMPLES = 5000
PSI_MODERATE_THRESHOLD = 0.1
PSI_HIGH_THRESHOLD = 0.2
_SMOOTHING = 1e-6


def _read_reference():
    try:
        reference = pd.read_csv(REFERENCE_DATA_PATH, usecols=FEATURE_NAMES)
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    if reference.empty or any(name not in reference.columns for name in FEATURE_NAMES):
        return None
    return reference


def _numeric_bins(values, thresholds):
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(numeric)
    bins = np.full(len(numeric), len(thresholds) + 1, dtype=int)
    bins[valid] = np.searchsorted(thresholds, numeric[valid], side="right")
    return bins


def _psi(reference_bins, recent_bins, bin_count):
    reference_counts = np.bincount(reference_bins, minlength=bin_count).astype(float)
    recent_counts = np.bincount(recent_bins, minlength=bin_count).astype(float)
    reference_share = (reference_counts + _SMOOTHING) / (
        reference_counts.sum() + _SMOOTHING * bin_count
    )
    recent_share = (recent_counts + _SMOOTHING) / (
        recent_counts.sum() + _SMOOTHING * bin_count
    )
    value = np.sum((recent_share - reference_share) * np.log(recent_share / reference_share))
    return float(value)


def _categorical_values(name, values):
    if name != "is_new_device":
        return values.astype("string").fillna("<missing>").astype(str)

    def normalize(value):
        if pd.isna(value):
            return "<missing>"
        if value is True or str(value).strip().casefold() in {"1", "true", "yes"}:
            return "1"
        if value is False or str(value).strip().casefold() in {"0", "false", "no"}:
            return "0"
        return str(value)

    return values.map(normalize)


def _feature_drift(name, reference, recent):
    if name in NUMERICAL_FEATURES:
        reference_values = pd.to_numeric(reference[name], errors="coerce").to_numpy(dtype=float)
        finite_reference = reference_values[np.isfinite(reference_values)]
        if finite_reference.size == 0:
            return None
        quantiles = np.unique(np.quantile(finite_reference, np.linspace(0, 1, 11)))
        thresholds = quantiles[1:-1]
        if thresholds.size == 0 and np.unique(finite_reference).size > 1:
            thresholds = np.array([(finite_reference.min() + finite_reference.max()) / 2])
        reference_bins = _numeric_bins(reference[name], thresholds)
        recent_bins = _numeric_bins(recent[name], thresholds)
        bin_count = len(thresholds) + 2
        reference_missing = int((~np.isfinite(reference_values)).sum())
        recent_values = pd.to_numeric(recent[name], errors="coerce").to_numpy(dtype=float)
        recent_missing = int((~np.isfinite(recent_values)).sum())
    else:
        reference_values = _categorical_values(name, reference[name])
        recent_values = _categorical_values(name, recent[name])
        categories = sorted(set(reference_values) | set(recent_values))
        category_index = {value: index for index, value in enumerate(categories)}
        reference_bins = reference_values.map(category_index).to_numpy(dtype=int)
        recent_bins = recent_values.map(category_index).to_numpy(dtype=int)
        bin_count = len(categories)
        reference_missing = int(reference[name].isna().sum())
        recent_missing = int(recent[name].isna().sum())

    psi_value = _psi(reference_bins, recent_bins, bin_count)
    if psi_value >= PSI_HIGH_THRESHOLD:
        level = "High shift"
    elif psi_value >= PSI_MODERATE_THRESHOLD:
        level = "Moderate shift"
    else:
        level = "Limited shift"
    return {
        "feature": name.replace("_", " ").title(),
        "psi": round(psi_value, 4),
        "level": level,
        "reference_missing": reference_missing,
        "recent_missing": recent_missing,
    }


def get_model_drift():
    reference = _read_reference()
    if reference is None:
        return {
            "status": "unavailable",
            "message": "The synthetic training reference is missing or does not match the saved model feature schema.",
            "reference_count": 0,
            "recent_count": 0,
            "features": [],
        }
    if len(reference) < MIN_REFERENCE_SAMPLES:
        return {
            "status": "insufficient",
            "message": (
                f"At least {MIN_REFERENCE_SAMPLES} compatible synthetic training rows "
                "are required for a reference distribution."
            ),
            "reference_count": len(reference),
            "recent_count": 0,
            "window_days": WINDOW_DAYS,
            "features": [],
        }

    window_start = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    feature_columns = [getattr(Transaction, name) for name in FEATURE_NAMES]
    rows = db.session.execute(
        db.select(*feature_columns)
        .where(Transaction.created_at >= window_start)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(MAX_RECENT_SAMPLES + 1)
    ).all()
    sample_capped = len(rows) > MAX_RECENT_SAMPLES
    recent = pd.DataFrame(rows[:MAX_RECENT_SAMPLES], columns=FEATURE_NAMES)
    if len(recent) < MIN_RECENT_SAMPLES:
        return {
            "status": "insufficient",
            "message": (
                f"At least {MIN_RECENT_SAMPLES} saved transactions from the last "
                f"{WINDOW_DAYS} days are required; drift is not calculated from a smaller sample."
            ),
            "reference_count": len(reference),
            "recent_count": len(recent),
            "window_days": WINDOW_DAYS,
            "features": [],
        }

    feature_rows = [
        _feature_drift(name, reference, recent)
        for name in FEATURE_NAMES
    ]
    features = [item for item in feature_rows if item is not None]
    return {
        "status": "available",
        "message": (
            "Feature distribution shifts are monitoring signals only. The reference is "
            "the synthetic educational training dataset; these values do not measure "
            "fraud prevalence, model accuracy, or confirmed fraud."
        ),
        "reference_count": len(reference),
        "recent_count": len(recent),
        "window_days": WINDOW_DAYS,
        "sample_capped": sample_capped,
        "features": features,
        "high_shift_count": sum(item["level"] == "High shift" for item in features),
        "moderate_shift_count": sum(item["level"] == "Moderate shift" for item in features),
    }
