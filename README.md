# Code Companion

Project author: Anshi (24CS044).

[![Tests](https://github.com/anshiladani/Code-Companion/actions/workflows/tests.yml/badge.svg)](https://github.com/anshiladani/Code-Companion/actions/workflows/tests.yml)

Code Companion is an early-stage Python learning demo with username-based practice profiles, adaptive problem recommendations, optional AI hints, and a responsive coding workspace.

## What works

- FastAPI API with interactive docs at `/docs` and a database-aware health check at `/health`.
- Password-protected profile registration and sign-in, with hashed passwords, private profile editing, login history, sign-out, and profile deletion.
- Six starter problems, seeded idempotently when the application starts.
- Recommendation by the closest problem difficulty to a learner's current rating.
- AI tutoring hints when `LLM_API_KEY` is configured.
- A responsive browser workspace that reports API errors instead of treating failed requests as successful.
- Docker Compose and Render Blueprint deployment configurations.
- GitHub Actions regression tests.

## Local development

Use Python 3.11 or newer. From the project directory in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./code_companion.db"
$env:ENABLE_LOCAL_CODE_EXECUTION = "true"
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. AI hints remain unavailable until an `LLM_API_KEY` is provided.

## Profile management

Create an account in the browser with a username, display name, and password of at least eight characters. Sign in with the same credentials to view or update your display name, see your own recent login history, sign out, or permanently delete your profile. Profile endpoints require the session's bearer token; recommendations are limited to the signed-in profile.

The database startup creates the authentication table and adds profile columns to existing databases without deleting existing profile records. Legacy username-only profiles are kept, but cannot be claimed or signed into because they have no password; register with a different username.

### Code execution warning

The local runner launches submitted Python in a child process, but it is **not a security sandbox**. It is disabled by default. Enabling `ENABLE_LOCAL_CODE_EXECUTION=true` is only suitable for a developer's own trusted code on a private machine. Never enable it on a public server or accept untrusted submissions with this runner. A public coding service needs a separately isolated execution provider/container per run, strict resource limits, and network/filesystem isolation.

## Docker Compose

1. Copy `.env.example` to `.env`.
2. Replace `POSTGRES_PASSWORD` with a long, unique password. Set `LLM_API_KEY` only if AI hints are needed.
3. Set `CORS_ORIGINS` to the exact browser origins that should be allowed. For a same-origin deployment, include the public site origin.
4. Start the stack:

```powershell
docker compose up --build -d
docker compose ps
```

The PostgreSQL service is not published on a host port. The web container runs as a non-root user. Local code execution stays disabled in the Compose configuration.

## Deploy a free demo on Render

The root-level `render.yaml` Blueprint creates the Docker web service and a private PostgreSQL database in Oregon. The database is not accessible from the public internet, and submitted code execution remains disabled.

1. Push this project to a GitHub repository. Confirm `.env`, virtual environments, and database files are not included.
2. Sign in to [Render](https://dashboard.render.com/), choose **New → Blueprint**, and connect the repository.
3. Select the repository's `render.yaml` and deploy the Blueprint. Render builds the Docker image, creates the database, and supplies `DATABASE_URL` to the web service.
4. When the service reports **Live**, open its `onrender.com` URL and check `/health`. The first visit may take about a minute after an idle period while a free service starts.
5. To enable optional AI hints, add `LLM_API_KEY` as a secret in the web service's Environment settings and redeploy. Leave it unset to keep hints disabled.

**Free-tier limitations:** Render's free web service spins down after 15 minutes without traffic, so the first visit after idle can be slow. A free PostgreSQL database expires 30 days after creation; after the additional 14-day upgrade grace period, Render deletes it and its data. Free databases do not include backups. This setup is for a temporary demo only—not a durable public launch. Upgrade the database before expiry and arrange backups before storing anything you need to keep. Render can also suspend free services when workspace usage limits are reached.

Profiles use password-based sign-in and are intended for a learning demo, not a production identity system. Existing username-only profiles are preserved but cannot be claimed without credentials; register with a different username. Do not enter sensitive personal information.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./code_companion.db` | SQLAlchemy database URL |
| `LLM_API_KEY` | unset | Enables the optional OpenAI hint integration |
| `CORS_ORIGINS` | localhost origins | Comma-separated exact browser origins |
| `ENABLE_LOCAL_CODE_EXECUTION` | `false` | Developer-only local execution toggle; unsafe for public use |
| `CODE_EXECUTION_TIMEOUT_SECONDS` | `3.0` | Local-runner wall-clock timeout |

## Before a public launch

This project is a learning demo, **not an industry-certified or production-ready service**:

- Add abuse/rate limiting, password reset, stronger session lifecycle controls, and account privacy safeguards before storing real learner data.
- Recommendations currently use the profile's static skill rating; assessed submissions and performance-based rating updates are not implemented yet.
- The practice problems are starter examples and do not yet have a judge, test cases, or submission history.
- Replace the local runner with an isolated code-execution service before accepting submissions from other people.
- Add database migrations and a tested backup/restore procedure before evolving a production database.
- Configure HTTPS, the production `CORS_ORIGINS`, monitoring, secrets management, and operational alerts at the hosting provider.
- Complete an independent security/privacy review, accessibility checks, and operational testing before real learners or sensitive data use it.

## Tests

```powershell
python -m unittest discover -s tests -v
```
