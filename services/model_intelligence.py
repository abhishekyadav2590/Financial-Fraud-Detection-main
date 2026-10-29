"""Read-only reporting for persisted model and evaluation artifacts."""
import json
from pathlib import Path

from model_schema import FEATURE_NAMES
from services.fraud_predictor import METADATA_PATH, MODEL_PATH, get_predictor

EVALUATION_ARTIFACTS_PATH = MODEL_PATH.parent / "evaluation_artifacts.json"
METRIC_EXPLANATIONS = {
    "accuracy": "Share of all test transactions classified correctly.",
    "precision": "Of transactions predicted as fraud, how many were actually fraud.",
    "recall": "Of actual fraud transactions, how many the model detected.",
    "f1_score": "Balance between fraud precision and recall.",
    "roc_auc": "How well the model ranks fraud above genuine activity across thresholds.",
    "pr_auc": "Precision-recall ranking quality, especially useful for minority fraud cases.",
}
METRIC_POINTS = {
    "accuracy": ["Measures overall classification correctness.", "Can be misleading when fraud is rare."],
    "precision": ["Measures correctness of fraud alerts.", "Higher precision means fewer false alarms."],
    "recall": ["Measures how many actual fraud cases were detected.", "Higher recall means fewer missed fraud cases."],
    "f1_score": ["Balances fraud precision and recall."],
    "roc_auc": ["Measures ranking quality across classification thresholds."],
    "pr_auc": ["Focuses on minority-class precision and recall.", "Useful for imbalanced fraud data."],
}
NUMERIC_LABELS = {"amount": "Amount", "transaction_hour": "Transaction Hour",
    "account_age_days": "Account Age", "transactions_last_24h": "Recent Transaction Count",
    "average_transaction_amount": "Average Transaction Amount", "amount_ratio": "Amount Relative to Average",
    "unusual_hour": "Unusual Hour", "young_account": "Young Account",
    "transaction_burst": "Transaction Burst", "new_device_unusual_location": "New Device + Unusual Location",
    "amount_spike_unusual_hour": "Amount Spike + Unusual Hour",
    "risky_context_burst": "Risky Transaction Context + Burst"}

def _load_json(path):
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, ValueError, TypeError):
        return None

def _human_feature(name):
    stripped = name.split("__", 1)[-1]
    if name.startswith("numerical__"):
        return NUMERIC_LABELS.get(stripped, stripped.replace("_", " ").title())
    fields = ("average_transaction_amount", "transactions_last_24h", "merchant_category",
              "transaction_type", "account_age_days", "transaction_hour",
              "is_new_device", "location_type", "device_type", "amount")
    for field in fields:
        prefix = field + "_"
        if stripped.startswith(prefix):
            value = stripped[len(prefix):]
            if field == "is_new_device":
                value = "Yes" if value == "1" else "No"
            return f"{field.replace('_', ' ').title()} = {value.replace('_', ' ').title()}"
    return stripped.replace("_", " ").title()

def _selection_summary(selected, comparison):
    selected_metrics = comparison.get(selected, {})
    if not selected_metrics:
        return "The persisted artifacts do not contain enough information to explain model selection."
    others = {name: values for name, values in comparison.items() if name != selected}
    if selected == "Logistic Regression" and "Calibrated Logistic Regression" in others:
        calibrated = others["Calibrated Logistic Regression"]
        pr_gap = abs(selected_metrics.get("pr_auc", 0) - calibrated.get("pr_auc", 0))
        f1_gap = abs(selected_metrics.get("f1_score", 0) - calibrated.get("f1_score", 0))
        return (f"{selected} was retained because its validation PR-AUC and F1 were within "
                f"{pr_gap:.4f} and {f1_gap:.4f} of the calibrated alternative, while preserving direct "
                "coefficient explainability. It also achieved stronger PR-AUC than the evaluated Random Forest.")
    return (f"{selected} was selected from the evaluated candidates using PR-AUC, F1, probability behavior, "
            "false-positive behavior, and interpretability rather than accuracy alone.")

def _selection_points(selected, comparison):
    selected_metrics = comparison.get(selected, {})
    if not selected_metrics:
        return ["Saved comparison details are not available."]
    points = [f"Selected model: {selected}.",
        f"Validation F1-score: {selected_metrics.get('f1_score', 0):.4f}.",
        f"Validation PR-AUC: {selected_metrics.get('pr_auc', 0):.4f}.",
        "Accuracy alone was not used for selection."]
    if selected == "Logistic Regression":
        points.append("Coefficient-based global and transaction explanations remain available.")
        if "Calibrated Logistic Regression" in comparison:
            calibrated = comparison["Calibrated Logistic Regression"]
            points.append(f"Calibration changed PR-AUC by {calibrated.get('pr_auc', 0) - selected_metrics.get('pr_auc', 0):+.4f} and F1 by {calibrated.get('f1_score', 0) - selected_metrics.get('f1_score', 0):+.4f}.")
    return points

def get_model_intelligence():
    metadata = _load_json(METADATA_PATH)
    artifacts = _load_json(EVALUATION_ARTIFACTS_PATH)
    if metadata is None:
        return {"available": False, "evaluation_available": False,
            "message": "Model metadata is not available. Run the model training workflow to generate it."}
    try:
        predictor = get_predictor()
        model_loaded = True
    except Exception:
        predictor = None; model_loaded = False
    comparison = artifacts.get("model_comparison", {}) if artifacts else {}
    influences = artifacts.get("feature_influence", []) if artifacts else []
    readable = [{"label": _human_feature(item["feature"]), "coefficient": item["coefficient"]}
                for item in influences]
    increasing = sorted((item for item in readable if item["coefficient"] > 0), key=lambda x: x["coefficient"], reverse=True)[:10]
    reducing = sorted((item for item in readable if item["coefficient"] < 0), key=lambda x: x["coefficient"])[:10]
    architecture = {}
    if predictor is not None:
        pipeline = predictor.pipeline
        classifier = pipeline.named_steps.get("classifier") if hasattr(pipeline, "named_steps") else None
        if classifier is not None and hasattr(classifier, "coef_"):
            architecture = {"type": "Binary Logistic Regression", "coefficient_count": int(classifier.coef_.size),
                "regularization": str(classifier.penalty), "solver": classifier.solver,
                "maximum_iterations": classifier.max_iter,
                "class_weight": classifier.class_weight if classifier.class_weight is not None else "None",
                "calibrated": False}
    metrics = metadata.get("held_out_test_metrics", {})
    matrix = metrics.get("confusion_matrix")
    confusion = None
    if isinstance(matrix, list) and len(matrix) == 2 and all(isinstance(row, list) and len(row) == 2 for row in matrix):
        confusion = {"tn": matrix[0][0], "fp": matrix[0][1], "fn": matrix[1][0], "tp": matrix[1][1]}
    return {"available": True, "evaluation_available": artifacts is not None,
        "evaluation_message": None if artifacts else "Evaluation artifacts are not available. Run the model training/evaluation workflow to generate them.",
        "model_loaded": model_loaded, "artifact_filename": MODEL_PATH.name,
        "metadata": metadata, "metrics": metrics, "metric_explanations": METRIC_EXPLANATIONS,
        "metric_points": METRIC_POINTS,
        "confusion": confusion, "artifacts": artifacts or {}, "comparison": comparison,
        "increasing_features": increasing, "reducing_features": reducing,
        "feature_chart": increasing[:7] + reducing[:7], "architecture": architecture,
        "selection_summary": _selection_summary(metadata.get("selected_model", "Unknown"), comparison),
        "selection_points": _selection_points(metadata.get("selected_model", "Unknown"), comparison),
        "feature_count": len(metadata.get("feature_names", FEATURE_NAMES)),
        "viva_points": ["This is supervised binary classification of fraud versus genuine transactions.",
            "The educational dataset is synthetic and fraud is the minority class.",
            f"The offline workflow evaluated {', '.join(comparison) if comparison else 'saved candidate models'}.",
            "Selection considers PR-AUC, recall, F1, probability quality, and false positives—not accuracy alone.",
            "The final classifier outputs a fraud probability and uses a separate validated decision threshold.",
            "Global coefficients describe general model influence; transaction explanations describe one specific prediction.",
            "Counterfactual analysis recomputes hypothetical inputs without changing saved transactions."]}
