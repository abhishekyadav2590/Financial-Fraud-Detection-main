"""Select, evaluate and serialize the fraud model reproducibly."""
import json
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import precision_recall_curve, roc_curve

from model_schema import (CATEGORICAL_FEATURES, FEATURE_NAMES, IDENTIFIER_COLUMN,
                          LOW_RISK_MAX, MEDIUM_RISK_MAX, MODEL_ARTIFACT_VERSION,
                          NUMERICAL_FEATURES, TARGET_COLUMN)
from prepare_data import ENGINEERED_NUMERICAL_FEATURES, RANDOM_STATE, prepare_data
from train_compare_models import (build_models, choose_threshold,
                                  evaluate_model, print_comparison, select_candidate)
from sanity_scenarios import MIXED_CASES, NORMAL_CONTROL, SUSPICIOUS_CONTROL

MODEL_DIRECTORY = Path(__file__).parent / "model"
MODEL_PATH = MODEL_DIRECTORY / "fraud_detection_pipeline.joblib"
METADATA_PATH = MODEL_DIRECTORY / "model_metadata.json"
EVALUATION_ARTIFACTS_PATH = MODEL_DIRECTORY / "evaluation_artifacts.json"

def _serializable_metrics(metrics):
    return {key: (value.tolist() if key == "confusion_matrix" else float(value))
            for key, value in metrics.items()
            if key not in {"classification_report", "probabilities"}}

def _compact_curve(*arrays, maximum_points=120):
    length = len(arrays[0])
    indices = np.unique(np.linspace(0, length - 1, min(length, maximum_points), dtype=int))
    return [[round(float(array[index]), 6) for index in indices] for array in arrays]

def main():
    X, y, X_train, X_val, X_test, y_train, y_val, y_test, _ = prepare_data()
    models, validation_results = build_models(), {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        threshold = choose_threshold(y_val, model.predict_proba(X_val)[:, 1])
        validation_results[name] = evaluate_model(model, X_val, y_val, threshold)
        validation_results[name]["threshold"] = threshold
    print("VALIDATION MODEL COMPARISON"); print_comparison(validation_results)
    selected_name, validation_metrics = select_candidate(validation_results)
    selected_model = models[selected_name]
    prediction_threshold = validation_metrics["threshold"]
    validation_probabilities = selected_model.predict_proba(X_val)[:, 1]
    # Risk tiers are centralized probability-communication bands. They are
    # deliberately independent from the validation-selected class threshold.
    low_max, medium_max = LOW_RISK_MAX, MEDIUM_RISK_MAX
    test_metrics = evaluate_model(selected_model, X_test, y_test, prediction_threshold)
    print("\nUNTOUCHED TEST METRICS"); print_comparison({selected_name: test_metrics})
    print("Confusion matrix [TN FP; FN TP]:", test_metrics["confusion_matrix"].tolist())

    # Test is now sealed; refit the same configuration on all available rows.
    final_pipeline = clone(selected_model).fit(X, y)
    MODEL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    joblib.dump(final_pipeline, MODEL_PATH)
    metadata = {
        "model_version": MODEL_ARTIFACT_VERSION,
        "selected_model": selected_name, "feature_names": FEATURE_NAMES,
        "numerical_features": NUMERICAL_FEATURES,
        "engineered_features": ENGINEERED_NUMERICAL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES, "target_column": TARGET_COLUMN,
        "excluded_columns": [IDENTIFIER_COLUMN], "training_row_count": len(X),
        "fraud_percentage": float(y.mean() * 100), "class_weight": None,
        "prediction_threshold": prediction_threshold,
        "risk_thresholds": {"low_max": low_max, "medium_max": medium_max},
        "validation_metrics": _serializable_metrics(validation_metrics),
        "held_out_test_metrics": _serializable_metrics(test_metrics),
        "random_state": RANDOM_STATE, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_methodology": {"train_percentage": 60, "validation_percentage": 20,
            "test_percentage": 20, "stratified": True, "test_set_used_for_selection": False},
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    test_probabilities = test_metrics["probabilities"]
    fpr, tpr, _ = roc_curve(y_test, test_probabilities)
    precision, recall, _ = precision_recall_curve(y_test, test_probabilities)
    compact_fpr, compact_tpr = _compact_curve(fpr, tpr)
    compact_precision, compact_recall = _compact_curve(precision, recall)
    histogram_edges = np.linspace(0, 1, 21)
    genuine_histogram = np.histogram(test_probabilities[np.asarray(y_test) == 0], bins=histogram_edges)[0]
    fraud_histogram = np.histogram(test_probabilities[np.asarray(y_test) == 1], bins=histogram_edges)[0]
    comparison = {name: _serializable_metrics(metrics) for name, metrics in validation_results.items()}
    feature_influence = []
    if selected_name == "Logistic Regression":
        names = final_pipeline.named_steps["preprocessing"].get_feature_names_out()
        coefficients = final_pipeline.named_steps["classifier"].coef_[0]
        feature_influence = [{"feature": str(name), "coefficient": round(float(coefficient), 8)}
                             for name, coefficient in zip(names, coefficients)]
    final_predict = lambda case: float(final_pipeline.predict_proba(pd.DataFrame([case], columns=FEATURE_NAMES))[0, 1])
    artifacts = {"artifact_version": MODEL_ARTIFACT_VERSION,
        "selected_model": selected_name, "comparison_split": "validation",
        "model_comparison": comparison,
        "roc_curve": {"false_positive_rate": compact_fpr, "true_positive_rate": compact_tpr,
                      "auc": float(test_metrics["roc_auc"])},
        "precision_recall_curve": {"precision": compact_precision, "recall": compact_recall,
                                   "auc": float(test_metrics["pr_auc"])},
        "probability_histogram": {"bin_edges": histogram_edges.round(2).tolist(),
            "genuine_counts": genuine_histogram.tolist(), "fraud_counts": fraud_histogram.tolist()},
        "dataset": {"type": "Synthetic educational transaction dataset", "row_count": len(X),
            "genuine_count": int((y == 0).sum()), "fraud_count": int((y == 1).sum()),
            "fraud_percentage": float(y.mean() * 100), "input_feature_count": len(FEATURE_NAMES),
            "target_column": TARGET_COLUMN},
        "feature_influence": feature_influence,
        "sanity_checks": {"normal_control_probability": final_predict(NORMAL_CONTROL),
            "suspicious_control_probability": final_predict(SUSPICIOUS_CONTROL),
            "mixed_probabilities": {name: final_predict(case) for name, case in MIXED_CASES.items()}},
    }
    EVALUATION_ARTIFACTS_PATH.write_text(json.dumps(artifacts, indent=2), encoding="utf-8")
    sample = pd.DataFrame([X.iloc[0].to_dict()], columns=FEATURE_NAMES)
    print(f"Saved {selected_name} to {MODEL_PATH}")
    print(f"Saved evaluation artifacts to {EVALUATION_ARTIFACTS_PATH}")
    print(f"Reload check probability: {joblib.load(MODEL_PATH).predict_proba(sample)[0, 1]:.6f}")
    print(f"Prediction threshold={prediction_threshold:.6f}; risk bands: LOW < {low_max:.6f}, MEDIUM < {medium_max:.6f}, HIGH otherwise")

if __name__ == "__main__":
    main()
