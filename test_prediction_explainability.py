import math
from sanity_scenarios import NORMAL_CONTROL, SUSPICIOUS_CONTROL
from model_schema import EXPLANATION_MINIMAL_MAX, FEATURE_NAMES
from services.fraud_predictor import FraudPredictor

def by_field(explanation):
    return {factor["field"]: factor for factor in explanation["factors"]}

def run_tests():
    predictor = FraudPredictor()
    before = predictor.predict(SUSPICIOUS_CONTROL)
    explanation = predictor.explain(SUSPICIOUS_CONTROL)
    after = predictor.predict(SUSPICIOUS_CONTROL)
    assert before == after  # explanation is read-only and cannot alter prediction
    assert abs(explanation["reconstructed_probability"] - before["fraud_probability"]) < 1e-6
    factors = by_field(explanation)
    assert set(factors) == set(FEATURE_NAMES)
    assert all("__" not in factor["label"] for factor in factors.values())
    assert factors["is_new_device"]["value"] == "New"
    assert factors["location_type"]["value"] == "Unusual Domestic"
    assert factors["is_new_device"]["contribution"] > 0
    assert factors["location_type"]["contribution"] > 0
    assert all(item["contribution"] > 0 for item in explanation["increasing"])
    assert all(item["contribution"] < 0 for item in explanation["reducing"])
    assert all(abs(item["contribution"]) < EXPLANATION_MINIMAL_MAX for item in explanation["neutral"])
    assert "53.3×" in " ".join(item["value"] for item in explanation["context"])
    assert str(SUSPICIOUS_CONTROL["transactions_last_24h"]) in " ".join(explanation["behavioral_observations"])
    assert "crypto" not in explanation["summary"].lower()  # not the current transaction type

    normal = predictor.explain(NORMAL_CONTROL)
    assert by_field(normal)["is_new_device"]["contribution"] < 0
    assert by_field(normal)["location_type"]["contribution"] < 0
    assert normal["reconstructed_probability"] < explanation["reconstructed_probability"]
    print("All prediction explainability tests passed.")

if __name__ == "__main__":
    run_tests()
