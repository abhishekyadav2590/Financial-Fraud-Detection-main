"""Train and compare classifiers with validation-only threshold selection."""
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
    classification_report, confusion_matrix, f1_score, precision_recall_curve,
    precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline

from prepare_data import RANDOM_STATE, TransactionFeatureEngineer, build_preprocessor, prepare_data

def _pipeline(classifier):
    return Pipeline([("feature_engineering", TransactionFeatureEngineer()),
                     ("preprocessing", build_preprocessor()), ("classifier", classifier)])

def build_models():
    # No class weights: balanced weights distort the probability base rate. The
    # decision threshold is tuned separately on validation data.
    raw_logistic = _pipeline(LogisticRegression(max_iter=2_000, random_state=RANDOM_STATE))
    return {
        "Logistic Regression": raw_logistic,
        "Calibrated Logistic Regression": CalibratedClassifierCV(
            _pipeline(LogisticRegression(max_iter=2_000, random_state=RANDOM_STATE)),
            method="sigmoid", cv=5),
        "Random Forest": _pipeline(RandomForestClassifier(
            n_estimators=400, min_samples_leaf=4, random_state=RANDOM_STATE, n_jobs=-1)),
    }

def choose_threshold(y_true, probabilities):
    precision, recall, thresholds = precision_recall_curve(y_true, probabilities)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.argmax(f1))])

def choose_risk_thresholds(y_true, probabilities, prediction_threshold):
    """Validation-derived bands: broad review tier and higher-confidence tier."""
    precision, recall, thresholds = precision_recall_curve(y_true, probabilities)
    # LOW boundary retains at least 90% of fraud above it; HIGH seeks >=40%
    # precision when attainable. These are risk tiers, not class decisions.
    recall_candidates = thresholds[recall[:-1] >= 0.90]
    low = float(recall_candidates[-1]) if len(recall_candidates) else prediction_threshold / 2
    high_candidates = thresholds[precision[:-1] >= 0.40]
    high = float(high_candidates[0]) if len(high_candidates) else max(prediction_threshold, float(np.quantile(probabilities, .98)))
    low = min(low, prediction_threshold)
    high = max(high, prediction_threshold)
    if high <= low:
        high = min(0.999999, low + 0.01)
    return low, high

def evaluate_model(model, X, y, threshold=0.5):
    probabilities = model.predict_proba(X)[:, 1]
    predictions = (probabilities >= threshold).astype(int)
    matrix = confusion_matrix(y, predictions, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    return {"accuracy": accuracy_score(y, predictions),
        "precision": precision_score(y, predictions, zero_division=0),
        "recall": recall_score(y, predictions, zero_division=0),
        "f1_score": f1_score(y, predictions, zero_division=0),
        "roc_auc": roc_auc_score(y, probabilities),
        "pr_auc": average_precision_score(y, probabilities),
        "brier_score": brier_score_loss(y, probabilities),
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0,
        "confusion_matrix": matrix,
        "classification_report": classification_report(y, predictions, target_names=["Genuine", "Fraud"], zero_division=0),
        "probabilities": probabilities}

def select_candidate(results):
    # PR-AUC measures rare-class ranking; Brier breaks close ties in favor of
    # probabilities that retain their literal meaning.
    best_name, best = max(results.items(), key=lambda item: (item[1]["pr_auc"], item[1]["f1_score"], -item[1]["brier_score"]))
    raw = results.get("Logistic Regression")
    # Prefer the directly interpretable, already probabilistic model when
    # calibration/complexity offers no material validation improvement.
    if raw and raw["pr_auc"] >= best["pr_auc"] - 0.005 and raw["f1_score"] >= best["f1_score"] - 0.005:
        return "Logistic Regression", raw
    return best_name, best

def print_comparison(results):
    print(f"{'Model':<32} {'Precision':>9} {'Recall':>8} {'F1':>8} {'ROC-AUC':>9} {'PR-AUC':>8} {'Brier':>8} {'FPR':>8}")
    for name, m in results.items():
        print(f"{name:<32} {m['precision']:>9.4f} {m['recall']:>8.4f} {m['f1_score']:>8.4f} {m['roc_auc']:>9.4f} {m['pr_auc']:>8.4f} {m['brier_score']:>8.4f} {m['false_positive_rate']:>8.4f}")

def main():
    _, _, X_train, X_val, X_test, y_train, y_val, y_test, _ = prepare_data()
    models, validation_results = build_models(), {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        threshold = choose_threshold(y_val, model.predict_proba(X_val)[:, 1])
        validation_results[name] = evaluate_model(model, X_val, y_val, threshold)
        validation_results[name]["threshold"] = threshold
    print("VALIDATION COMPARISON"); print_comparison(validation_results)
    name, selected = select_candidate(validation_results)
    print(f"\nSelected: {name}; validation threshold={selected['threshold']:.6f}")
    print("\nUNTOUCHED TEST RESULT"); print_comparison({name: evaluate_model(models[name], X_test, y_test, selected['threshold'])})

if __name__ == "__main__":
    main()
