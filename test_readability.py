from pathlib import Path

from app import app
from sanity_scenarios import SUSPICIOUS_CONTROL
from services.counterfactual_explainer import analyze_counterfactuals
from services.fraud_predictor import FraudPredictor

ROOT = Path(__file__).parent

def run_tests():
    predictor = FraudPredictor()
    prediction_before = predictor.predict(SUSPICIOUS_CONTROL)
    counterfactual_before = analyze_counterfactuals(predictor, SUSPICIOUS_CONTROL)

    # Compile every template to catch malformed Jinja introduced by presentation edits.
    with app.app_context():
        for template_name in app.jinja_env.list_templates():
            app.jinja_env.get_template(template_name)

    detail = (ROOT / "templates" / "transactions" / "detail.html").read_text(encoding="utf-8")
    counterfactual = (ROOT / "templates" / "transactions" / "counterfactual.html").read_text(encoding="utf-8")
    investigator = (ROOT / "templates" / "statement" / "investigation.html").read_text(encoding="utf-8")
    statement = (ROOT / "templates" / "statement" / "results.html").read_text(encoding="utf-8")
    intelligence = (ROOT / "templates" / "admin" / "model_intelligence.html").read_text(encoding="utf-8")
    assert 'class="explanation-list' in detail
    assert 'class="explanation-list' in counterfactual
    assert 'class="explanation-list' in investigator
    assert "join('; ')" not in statement
    assert "selection_points" in intelligence and "metric_points" in intelligence

    prediction_after = predictor.predict(SUSPICIOUS_CONTROL)
    counterfactual_after = analyze_counterfactuals(predictor, SUSPICIOUS_CONTROL)
    assert prediction_after == prediction_before
    assert counterfactual_after["baseline"] == counterfactual_before["baseline"]
    assert [(item["changes"], item["new_probability"]) for item in counterfactual_after["one_feature"]] == [
        (item["changes"], item["new_probability"]) for item in counterfactual_before["one_feature"]]
    print("All readability and calculation-invariance tests passed.")

if __name__ == "__main__":
    run_tests()
