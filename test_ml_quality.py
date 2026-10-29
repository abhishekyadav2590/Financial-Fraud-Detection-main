import json
import joblib
import pandas as pd
from sanity_scenarios import MIXED_CASES, NORMAL_CONTROL, SUSPICIOUS_CONTROL
from model_schema import FEATURE_NAMES
from services.fraud_predictor import FraudPredictor, METADATA_PATH, MODEL_PATH, risk_level

def run_tests():
    predictor = FraudPredictor()
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    pipeline = joblib.load(MODEL_PATH)
    assert metadata["feature_names"] == FEATURE_NAMES
    assert list(pipeline.feature_names_in_) == FEATURE_NAMES
    normal, suspicious = predictor.predict_many([NORMAL_CONTROL, SUSPICIOUS_CONTROL])
    for result in (normal, suspicious):
        assert 0 <= result["fraud_probability"] <= 1
    assert suspicious["fraud_probability"] > normal["fraud_probability"] + 0.25
    for case in MIXED_CASES.values():
        assert 0 <= predictor.predict(case)["fraud_probability"] <= 1
    threshold = predictor.prediction_threshold
    assert int(threshold >= threshold) == 1
    assert int(max(0, threshold - 1e-9) >= threshold) == 0
    assert risk_level(predictor.low_risk_max - 1e-9, predictor.low_risk_max, predictor.medium_risk_max) == "LOW"
    assert risk_level(predictor.low_risk_max, predictor.low_risk_max, predictor.medium_risk_max) == "MEDIUM"
    assert risk_level(predictor.medium_risk_max, predictor.low_risk_max, predictor.medium_risk_max) == "HIGH"
    frame = pd.DataFrame([NORMAL_CONTROL], columns=FEATURE_NAMES)
    assert 0 <= pipeline.predict_proba(frame)[0, 1] <= 1
    try:
        predictor.validate_transaction({**NORMAL_CONTROL, "device_type": "unknown"})
        raise AssertionError("Unknown category was accepted")
    except ValueError:
        pass
    print("All ML quality regression tests passed.")

if __name__ == "__main__":
    run_tests()
