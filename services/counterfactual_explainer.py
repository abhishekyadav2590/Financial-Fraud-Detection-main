"""Bounded, model-backed counterfactual sensitivity analysis.

This module never mutates or persists transactions. Every hypothetical row is
validated and scored by FraudPredictor using the deployed sklearn pipeline.
"""
from itertools import combinations

from model_schema import (COUNTERFACTUAL_MINIMAL_MAX, COUNTERFACTUAL_MODERATE_MAX,
    COUNTERFACTUAL_SLIGHT_MAX, FEATURE_NAMES, VALID_CATEGORIES)

MAX_COMBINED_SCENARIOS = 3
RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
LABELS = {"amount": "Amount", "transaction_type": "Transaction type",
    "transaction_hour": "Transaction hour", "device_type": "Device type",
    "is_new_device": "New device", "location_type": "Location",
    "merchant_category": "Merchant category", "account_age_days": "Account age",
    "transactions_last_24h": "Transactions in last 24 hours",
    "average_transaction_amount": "Average transaction amount"}

def _impact(delta):
    magnitude = abs(delta)
    if magnitude < COUNTERFACTUAL_MINIMAL_MAX:
        return "Minimal change"
    strength = "Slightly" if magnitude < COUNTERFACTUAL_SLIGHT_MAX else "Moderately" if magnitude < COUNTERFACTUAL_MODERATE_MAX else "Strongly"
    return f"{strength} {'increases' if delta > 0 else 'reduces'} model risk"

def _display(field, value):
    if field in {"amount", "average_transaction_amount"}:
        return f"₹{float(value):,.2f}"
    if field == "transaction_hour":
        return f"{int(value):02d}:00"
    if field == "is_new_device":
        return "Yes" if int(value) else "No"
    if field == "account_age_days":
        return f"{int(value):,} days"
    return str(value).replace("_", " ").title()

def _candidate_changes(original):
    average = max(float(original["average_transaction_amount"]), 1.0)
    candidates = []
    def add(field, values, note=None):
        seen = {original[field]}
        for value in values:
            if value not in seen:
                seen.add(value); candidates.append(({field: value}, note))
    add("is_new_device", [1 - int(original["is_new_device"])])
    add("location_type", ["usual", "unusual_domestic", "international"])
    add("transaction_hour", [2, 10, 14, 18])
    add("amount", [round(average, 2), round(average * 2, 2), round(average * 5, 2), round(max(float(original["amount"]) * .5, 1), 2)])
    add("transactions_last_24h", [1, 2, 3, 10, 15])
    add("account_age_days", [365, 1000], "Hypothetical model sensitivity only; account age cannot be changed operationally.")
    add("transaction_type", VALID_CATEGORIES["transaction_type"])
    add("device_type", VALID_CATEGORIES["device_type"])
    return candidates

def _scenario(predictor, original, baseline, changes, kind, note=None, baseline_explanation=None):
    hypothetical = {**original, **changes}
    result = predictor.predict(hypothetical)
    delta = result["fraud_probability"] - baseline["fraud_probability"]
    changed = [{"field": field, "label": LABELS[field], "before": _display(field, original[field]),
                "after": _display(field, value)} for field, value in changes.items()]
    transition = None
    if result["risk_level"] != baseline["risk_level"]:
        transition = f"{baseline['risk_level']} → {result['risk_level']}"
    contribution_changes = []
    if baseline_explanation is not None:
        after_explanation = predictor.explain(hypothetical)
        before_map = {item["field"]: item for item in baseline_explanation["factors"]}
        after_map = {item["field"]: item for item in after_explanation["factors"]}
        for field in changes:
            contribution_changes.append({"label": LABELS[field],
                "before": before_map[field]["contribution"], "after": after_map[field]["contribution"]})
    direction = "increased" if delta > 0 else "reduced" if delta < 0 else "did not change"
    change_text = ", ".join(f"{item['label']} from {item['before']} to {item['after']}" for item in changed)
    explanation = f"Changing {change_text} {direction} predicted fraud probability by {abs(delta) * 100:.2f} percentage points. This is a hypothetical model sensitivity result."
    amount_context = None
    if "amount" in changes:
        avg = max(float(hypothetical["average_transaction_amount"]), 1)
        amount_context = {"original_amount": _display("amount", original["amount"]),
            "average_amount": _display("average_transaction_amount", avg),
            "hypothetical_amount": _display("amount", hypothetical["amount"]),
            "original_ratio": float(original["amount"]) / avg,
            "hypothetical_ratio": float(hypothetical["amount"]) / avg}
    return {"kind": kind, "changes": changes, "changed_fields": changed,
        "new_probability": result["fraud_probability"], "new_prediction": result["prediction"],
        "new_risk_level": result["risk_level"], "absolute_change": abs(delta),
        "percentage_point_change": delta * 100, "impact": _impact(delta),
        "risk_band_transition": transition, "explanation": explanation,
        "note": note, "amount_context": amount_context,
        "model_contribution_changes": contribution_changes}

def analyze_counterfactuals(predictor, raw_transaction, stored_baseline=None):
    original = predictor.validate_transaction(raw_transaction)
    baseline = stored_baseline or predictor.predict(original)
    baseline_explanation = predictor.explain(original) if predictor.metadata.get("selected_model") == "Logistic Regression" else None
    one_feature = [_scenario(predictor, original, baseline, changes, "one_feature", note, baseline_explanation)
                   for changes, note in _candidate_changes(original)]
    reducing = sorted((item for item in one_feature if item["percentage_point_change"] < 0), key=lambda item: item["new_probability"])
    increasing = sorted((item for item in one_feature if item["percentage_point_change"] > 0), key=lambda item: item["new_probability"], reverse=True)

    # Combine only the strongest distinct one-field reducers; never brute force.
    best_by_field = {}
    for item in reducing:
        field = next(iter(item["changes"]))
        best_by_field.setdefault(field, item)
    influential = list(best_by_field.values())[:3]
    combined = []
    for size in (2, 3):
        for selected in combinations(influential, size):
            changes = {}
            for item in selected:
                changes.update(item["changes"])
            combined.append(_scenario(predictor, original, baseline, changes, "combined", baseline_explanation=baseline_explanation))
            if len(combined) >= MAX_COMBINED_SCENARIOS:
                break
        if len(combined) >= MAX_COMBINED_SCENARIOS:
            break
    combined.sort(key=lambda item: (len(item["changes"]), item["new_probability"]))
    lower_band = [item for item in one_feature + combined
                  if RISK_RANK[item["new_risk_level"]] < RISK_RANK[baseline["risk_level"]]]
    minimal = min(lower_band, key=lambda item: (len(item["changes"]), item["new_probability"])) if lower_band else None
    return {"original": original, "baseline": baseline, "one_feature": one_feature,
        "reducing": reducing, "increasing": increasing, "combined": combined,
        "minimal_lower_band": minimal, "max_combined_scenarios": MAX_COMBINED_SCENARIOS,
        "interpretation": "Counterfactuals show how the trained model reacts to hypothetical inputs. They do not prove causality, change the saved transaction, or provide guidance for bypassing monitoring."}

def analyze_custom_scenario(predictor, original, hypothetical, stored_baseline=None):
    original = predictor.validate_transaction(original)
    hypothetical = predictor.validate_transaction(hypothetical)
    changes = {field: hypothetical[field] for field in FEATURE_NAMES if hypothetical[field] != original[field]}
    baseline = stored_baseline or predictor.predict(original)
    if not changes:
        return _scenario(predictor, original, baseline, {}, "custom")
    explanation = predictor.explain(original) if predictor.metadata.get("selected_model") == "Logistic Regression" else None
    return _scenario(predictor, original, baseline, changes, "custom", baseline_explanation=explanation)
