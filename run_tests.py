import subprocess
import sys
from pathlib import Path


TEST_SUITES = (
    "test_admin.py",
    "test_admin_commands.py",
    "test_admin_audit.py",
    "test_audit.py",
    "test_auth.py",
    "test_bulk_prediction.py",
    "test_counterfactual.py",
    "test_dashboard.py",
    "test_fraud_investigator.py",
    "test_fraud_assistant_chat.py",
    "test_drift_monitor.py",
    "test_ml_quality.py",
    "test_model_intelligence.py",
    "test_prediction_api.py",
    "test_prediction_explainability.py",
    "test_readability.py",
    "test_statement_analyzer.py",
    "test_transactions.py",
)


def main():
    project_root = Path(__file__).resolve().parent
    passed = 0
    failed = 0

    for test_file in TEST_SUITES:
        print(f"\n=== {test_file} ===", flush=True)
        result = subprocess.run(
            [sys.executable, str(project_root / test_file)],
            cwd=project_root,
            check=False,
        )
        if result.returncode == 0:
            passed += 1
        else:
            failed += 1

    print("\n=== Test summary ===")
    print(f"Total test suites: {len(TEST_SUITES)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("Skipped: 0")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
