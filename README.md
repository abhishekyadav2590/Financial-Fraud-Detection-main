# AI-Powered Data Analytics for Fraud Detection in Financial Transactions

**Product:** FinShield AI

A college project demonstrating an end-to-end fraud risk workflow with Flask and Scikit-learn. The application supports user accounts, transaction analysis, prediction history, administrator review, dashboard analytics, and bounded bulk CSV analysis. Model results are risk estimates for human review, not definitive fraud determinations.

> **Research and safety boundary:** this project uses a generated educational dataset. Its model and scores have not been validated on real financial activity and must not be used to approve, deny, block, or investigate real customer transactions without independent validation and accountable human review.

## Current capabilities

- Registration, login, logout, password hashing, CSRF-protected browser forms, and role-based access control
- Raw transaction prediction through one saved preprocessing-and-classifier pipeline
- Model-faithful single-transaction Logistic Regression explanations with grouped contributions and context
- Protected counterfactual model-sensitivity analysis with bounded scenarios and a temporary what-if simulator
- Admin-only Model Intelligence Center backed by persisted evaluation artifacts and held-out curves
- User transaction history and risk summaries
- Administrator dashboards, review status updates, filters, and pagination
- Admin-only CSV bulk analysis with row/file limits and CSV/PDF reports
- Authenticated CSV/XLSX statement analysis with behavioral anomaly ranking
- Owner-scoped, temporary statement results; admin-scoped, temporary bulk results
- Atomic transaction and analyst-review writes, plus a read-only review audit log
- Security response headers and `no-store` caching on dynamic responses

## Local setup

### Windows quick start

```powershell
git clone <PRIVATE_REPOSITORY_URL>
Set-Location .\Financial-Fraud-Detection-main
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\start_demo.bat
```

Install 64-bit **Python 3.12** first and ensure the Python Launcher (`py`) is available. `requirements.txt` lists pinned application dependencies; `requirements.lock` records the complete tested environment. Use the same lock for team setup and update it only after validating dependency changes.

The Windows launcher creates `.venv` and installs the lock if needed, runs the database migrations without deleting existing data, starts the Flask app once, waits for its model health check, and opens the local URL. Or run the equivalent steps manually:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m flask --app app db upgrade
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000/** on the same laptop. The app uses a local SQLite database at `instance/fraud_detection.db` by default. A fresh clone creates its own database when migrations run; existing local databases are upgraded in place, not reset. No `.env` file or hosted service is required for a local demo: development uses a process-local generated session key and the SQLite default. The launcher refuses to run migrations if a local `.env` or environment variable points to a non-SQLite database; configure a local SQLite URL before using it. Never commit `.env` or database files.

To create a local administrator for the demo, run the following and enter a private password at the hidden prompt:

```powershell
.\.venv\Scripts\python.exe -m flask --app app create-admin
```

Normal users can register through the app. Each teammate should create their own local admin if needed; do not share passwords or your local database. To stop the demo, close the **FinShield AI server** console opened by `start_demo.bat`.

Run the full tests with:

```powershell
.\.venv\Scripts\python.exe run_tests.py
```

### Share with your team

The local Git repository is initialized, but has no commits or remote. The repository should be **private** because it contains project code and the saved model. Before sharing, review `git status` and confirm `.env`, `.venv`, and `instance/fraud_detection.db` are ignored; then stage and commit the reviewed project in VS Code. Use **Publish to GitHub → Private repository** to create and push to GitHub, and invite teammates as collaborators in repository settings. Do not push this local database, `.env`, passwords, or real transaction data. No GitHub repository has been created or pushed by this setup.

Teammates clone the private repository, install Python 3.12, follow the Windows quick start, and register their own users locally. Each teammate's localhost and database are private to their own machine; this does not create a shared live demo.

## Model and dataset

The reproducible synthetic dataset is stored at `dataset/transactions.csv`. The deployed artifact is `model/fraud_detection_pipeline.joblib`; its matching schema and evaluation details are in `model/model_metadata.json`. The pipeline accepts the raw feature schema and performs preprocessing internally.

The dataset and model can be recreated with the commands below. **These commands overwrite the current generated dataset and saved model/evaluation artifacts. Use a separate working copy and preserve a backup before retraining.**

```powershell
.\.venv\Scripts\python.exe generate_dataset.py
.\.venv\Scripts\python.exe train_compare_models.py
.\.venv\Scripts\python.exe train_final_model.py
.\.venv\Scripts\python.exe evaluate_ml.py
```

## Tests

Run all focused workflow suites with:

```powershell
.\.venv\Scripts\python.exe run_tests.py
```

The 18 suites cover authentication and authorization, prediction validation, model/schema consistency, sanity-case ordering, threshold boundaries, user transactions, dashboards, administrator review and audit, model monitoring, assistant behavior, bulk CSV analysis and reports, and statement analysis.

## Research preparation

See [Research readiness](./docs/RESEARCH_READINESS.md) for the verified dataset/model facts, reported held-out results, research questions, reproducibility constraints, ethical limitations, and a suggested study structure. The stored metrics describe a synthetic educational experiment, not real-world fraud performance.

## Smart Statement Analyzer

Authenticated users can open `/statement-analyzer` and upload a Paytm-style or generic CSV/XLSX statement. Common column variants are detected automatically. The original upload is processed in memory and is never saved; detailed results remain in an owner-scoped temporary cache for approximately 30 minutes.

Statement rows receive an explainable behavioral anomaly score based on amount deviation, unusual activity time, frequency, merchant novelty, transaction-mode rarity, recent spending, and repeated-payment signals. The saved fraud model is not invoked when imported rows lack its required device, location, account-age, and merchant-category fields.

Medium- and high-risk rows include an **AI Investigate** action. The deterministic local investigator produces an investigation score, evidence and counter-evidence, risk-pattern explanation, explicit evidence coverage, behavior comparison, nearby transaction timeline, recommended human checks, radar chart, and downloadable PDF. No external AI service or API key is required, and the investigator never changes an administrator's review decision automatically.

## Scope and limitations

- The data is synthetic and the model is educational; it is not validated for real financial decisions.
- Bulk analysis results are held temporarily in application memory and are not a durable job queue.
- The Flask development server is for local demonstration only. A shared public or network-accessible demo requires separate hosting authorization and production configuration; this project does not deploy or provision paid services.
- Bulk and statement analysis caches are process-local; they are not durable and are not shared across multiple application workers.
- This project does not include new model families, external APIs, payment integrations, or deployment infrastructure.
