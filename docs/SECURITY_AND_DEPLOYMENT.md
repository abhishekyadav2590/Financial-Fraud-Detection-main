# Security and deployment notes

This note records controls verified in the repository and the remaining work before any deployment beyond local educational use. It is not a certification or a guarantee that the application is free of vulnerabilities.

## Verified application controls

- Passwords are stored with Werkzeug password hashing. Login failures use a generic message, and account roles are checked by server-side decorators.
- Browser forms use Flask-WTF CSRF protection. Logout is a protected POST. The unauthenticated JSON prediction endpoint is CSRF-exempt because it does not use cookie authentication or mutate application state; it accepts only a JSON object and validates its fields through the saved prediction pipeline.
- Login `next_url` values are limited to root-relative local paths. Absolute, protocol-relative, backslash-containing, and control-character targets are rejected.
- Dynamic responses include `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and a restrictive `Permissions-Policy`; dynamic endpoints are marked `Cache-Control: no-store`. Static assets retain their normal caching behavior.
- Administrator routes use server-side role authorization. Transaction views are account-scoped, statement-analysis results are user-scoped, and bulk analyses are admin-scoped.
- File input is bounded by the Flask request-size limit and feature-specific byte/row limits. Uploaded statements are analyzed in memory rather than saved as uploaded files.
- Templates use Jinja autoescaping; CSV reports neutralize formula-like leading content. SQL access uses SQLAlchemy query expressions.
- Transaction writes and analyst review/audit updates are committed atomically. Model predictions are distinct from human review states.
- Production configuration fails closed unless a sufficiently long `SECRET_KEY`, PostgreSQL URL, disabled debug mode, and secure session cookies are configured.

## Step 9 checks

The following checks were run with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m compileall -q app.py auth\routes.py test_auth.py test_prediction_api.py
.\.venv\Scripts\python.exe test_auth.py
.\.venv\Scripts\python.exe test_prediction_api.py
.\.venv\Scripts\python.exe run_tests.py
```

The final full test run completed 18 suites: 18 passed, 0 failed, 0 skipped. The suites deliberately log CSRF rejections and simulated database exceptions; these are expected test cases.

Manual source searches found no direct use of `eval`, `exec`, `os.system`, `shell=True`, unsafe YAML loading, `pickle.load`, or explicit `Markup` construction in the application modules. SQL query execution found by the search uses SQLAlchemy `select` expressions.

No `pip-audit`, Bandit, or Safety scanner was installed in the existing virtual environment. `pip check` verifies dependency consistency only; it is **not** a CVE audit. Direct dependencies are pinned in `requirements.txt`; the complete tested environment is captured in `requirements.lock`. The lock records this project's Windows/Python 3.12.3 test environment.

## Remaining deployment risks and required decisions

1. **Secret management:** local development falls back to a generated process-local secret when unset; `APP_ENV=production` now rejects that configuration unless an environment-provided key of at least 32 characters is present. Configure one strong, private, persistent secret shared by application workers before deployment. Rotating it invalidates existing sessions. Never publish `.env` values.
2. **HTTPS and cookies:** local configuration defaults `SESSION_COOKIE_SECURE` to false. Enable it behind correctly configured HTTPS, and verify any reverse proxy's forwarded-protocol handling. Do not trust arbitrary forwarded headers.
3. **Request throttling:** there is no application-level login or prediction rate limit. The prediction endpoint is unauthenticated and CSRF-exempt by design, so deployments that expose it publicly need network/API-gateway rate limiting, quotas, monitoring, and an abuse response plan.
4. **Host and proxy policy:** configure allowed hosts at the edge/application deployment layer. The redirect fix avoids trusting the `Host` header for the `next_url` destination, but this is not a substitute for trusted proxy and host validation.
5. **Content Security Policy:** no CSP is set. The current templates load fonts and JavaScript/CSS from external CDNs and include page scripts; define and test a restrictive CSP before deployment rather than applying a policy that silently breaks these features.
6. **Dependency advisories:** `requirements.txt` pins direct dependencies and `requirements.lock` records the tested environment. A prior `pip-audit` run against an earlier lock snapshot reported no known vulnerabilities; rerun an advisory scan against the current lock before any future release.
7. **Production operations:** production deployment is outside this project's current local-demo scope. The development server, local SQLite database, process-local analysis caches, and current operational controls are not a production hosting configuration.
8. **Model governance:** the dataset and model are synthetic and educational, and the saved evaluation does not establish operational suitability. Do not use the model to make real financial decisions without representative approved data, independent validation, calibration/threshold review, monitoring, privacy review, and human governance.

## Local safeguards

- Keep `FLASK_DEBUG=false` except during local development.
- Do not commit `.env`, database files, uploaded statements, user data, or model credentials.
- Take a database backup before schema migrations on a database containing data.
- Create administrators only through the interactive CLI and protect access to the machine and database.
- Review the deployment and research caveats in [Research readiness](./RESEARCH_READINESS.md) before presenting model results.
- No hosting provider, paid service, remote database, or public URL is configured or provisioned. The documented URL is local to the computer running the app.
