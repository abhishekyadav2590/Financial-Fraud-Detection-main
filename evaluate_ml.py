"""Produce a presentation-friendly audit of the saved educational ML system."""
import json
from pathlib import Path
import joblib
import pandas as pd

from model_schema import CATEGORICAL_FEATURES, NUMERICAL_FEATURES
from services.fraud_predictor import FraudPredictor
from sanity_scenarios import MIXED_CASES, NORMAL_CONTROL, SUSPICIOUS_CONTROL
from prepare_data import prepare_data
from train_compare_models import build_models

ROOT = Path(__file__).parent
REPORT_PATH = ROOT / "model" / "ml_evaluation_report.json"
def build_report():
    data = pd.read_csv(ROOT / "dataset" / "transactions.csv")
    metadata = json.loads((ROOT / "model" / "model_metadata.json").read_text(encoding="utf-8"))
    predictor = FraudPredictor()
    counts = data["is_fraud"].value_counts().to_dict()
    numeric = data.groupby("is_fraud")[NUMERICAL_FEATURES].agg(["mean", "median"]).round(4)
    categorical = {column: pd.crosstab(data[column], data.is_fraud, normalize="columns").round(4).to_dict()
                   for column in CATEGORICAL_FEATURES}
    correlations = data[NUMERICAL_FEATURES + ["is_fraud"]].corr(numeric_only=True)["is_fraud"].drop("is_fraud").sort_values(key=abs, ascending=False)
    report = {
        "dataset": {"rows": len(data), "genuine": int(counts.get(0, 0)), "fraud": int(counts.get(1, 0)),
                    "fraud_ratio": float(data.is_fraud.mean()), "missing_values": int(data.isna().sum().sum()),
                    "duplicate_transaction_ids": int(data.transaction_id.duplicated().sum())},
        "numeric_by_class": {str(index): {str(k): float(v) for k, v in row.items()} for index, row in numeric.iterrows()},
        "categorical_distributions": categorical,
        "numeric_target_correlations": correlations.round(4).to_dict(),
        "selected_model": metadata["selected_model"], "class_weight": metadata["class_weight"],
        "prediction_threshold": metadata["prediction_threshold"], "risk_thresholds": metadata["risk_thresholds"],
        "held_out_test_metrics": metadata["held_out_test_metrics"],
        "scenarios": {"normal_control": predictor.predict(NORMAL_CONTROL),
                      "suspicious_control": predictor.predict(SUSPICIOUS_CONTROL),
                      **{name: predictor.predict(case) for name, case in MIXED_CASES.items()}},
    }
    pipeline = joblib.load(ROOT / "model" / "fraud_detection_pipeline.joblib")
    if metadata["selected_model"] == "Logistic Regression":
        names = pipeline.named_steps["preprocessing"].get_feature_names_out()
        classifier = pipeline.named_steps["classifier"]
        coefficients = pd.Series(classifier.coef_[0], index=names).sort_values()
        report["logistic_regression"] = {"intercept": float(classifier.intercept_[0]),
            "most_negative_coefficients": coefficients.head(10).round(6).to_dict(),
            "most_positive_coefficients": coefficients.tail(10).sort_values(ascending=False).round(6).to_dict()}
        _, _, X_train, _, X_test, y_train, _, y_test, _ = prepare_data()
        audit_model = build_models()["Logistic Regression"].fit(X_train, y_train)
        held_out = pd.DataFrame({"probability": audit_model.predict_proba(X_test)[:, 1], "label": y_test.to_numpy()})
        quantiles = [0, .1, .25, .5, .75, .9, .95, .99, 1]
        report["held_out_probability_distribution"] = {
            "overall": held_out.probability.quantile(quantiles).round(6).to_dict(),
            "genuine": held_out.loc[held_out.label == 0, "probability"].quantile(quantiles).round(6).to_dict(),
            "fraud": held_out.loc[held_out.label == 1, "probability"].quantile(quantiles).round(6).to_dict()}
    return report

def main():
    report = build_report()
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    metrics = report["held_out_test_metrics"]
    print(f"Rows={report['dataset']['rows']:,}; fraud={report['dataset']['fraud']:,} ({report['dataset']['fraud_ratio']:.2%})")
    print(f"Model={report['selected_model']}; threshold={report['prediction_threshold']:.4f}")
    print(f"Precision={metrics['precision']:.4f}; Recall={metrics['recall']:.4f}; F1={metrics['f1_score']:.4f}; ROC-AUC={metrics['roc_auc']:.4f}; PR-AUC={metrics['pr_auc']:.4f}")
    print(f"Confusion matrix [TN FP; FN TP]={metrics['confusion_matrix']}")
    print(f"Normal={report['scenarios']['normal_control']['fraud_probability']:.2%}; Suspicious={report['scenarios']['suspicious_control']['fraud_probability']:.2%}")
    print(f"Detailed report: {REPORT_PATH}")

if __name__ == "__main__":
    main()
