# Paran Bank

Paran Bank is a self-contained, responsive online-banking **prototype** built with Python 3, Flask, Jinja, SQLAlchemy, and SQLite by default. It includes customer registration and sign-in, a simulated-balance dashboard, deposits and withdrawals, and an environment-provisioned administrator area.

> **Prototype notice:** Paran Bank is not a real bank or financial service. Balances and transactions are simulated. No real funds are held, transferred, or connected to a bank.

## Requirements

- Python 3.10 or later
- pip
- PostgreSQL only if you choose a hosted PostgreSQL database

## Run locally

From this directory, create and activate a virtual environment, then install dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set a session secret and optional admin credentials in your PowerShell session before running:

```powershell
$env:SECRET_KEY = "use-a-long-random-value-for-local-development"
$env:ADMIN_USERNAME = "your_admin_name"
$env:ADMIN_PASSWORD = "use-a-unique-password-at-least-12-characters"
python app.py
```

Open <http://127.0.0.1:5000>. To start without an administrator, leave both `ADMIN_USERNAME` and `ADMIN_PASSWORD` unset. There are no public default admin accounts or built-in credentials. The app creates its SQLite database at `instance/paran_bank.db` on first run. For local-only convenience, `SECRET_KEY` has a random process-specific fallback; set it explicitly if you need sessions to survive restarts.

All forms use CSRF protection. Customer passwords are stored as Werkzeug password hashes; usernames are validated and unique without regard to case. The administrator dashboard is only provisioned when both admin environment variables are set. When those variables identify an existing admin account, its password hash is updated at startup to support credential rotation.

## Tests

```powershell
python -m pytest -q
```

The focused test suite covers registration, password hashing, duplicate usernames, login and logout, role authorization, deposits and withdrawals, and persistence across app instances.

## Deploy to Render

Create a Render Web Service from this project, or use the included `render.yaml` Blueprint. Configure:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app`
- `SECRET_KEY`: a long, unique secret (Render can generate this)
- `ADMIN_USERNAME` and `ADMIN_PASSWORD`: set both to provision the administrator; use unique credentials
- `DATABASE_URL`: the connection string from a PostgreSQL service for persistent hosted data

The included Blueprint provisions a PostgreSQL database and connects it to the web service. If deploying without the Blueprint, create a PostgreSQL service yourself and set `DATABASE_URL` on the web service. PostgreSQL URLs beginning with `postgres://` or `postgresql://` are normalized for the included psycopg2 driver.

SQLite on Render's free service uses temporary storage. Its database can be lost when the service restarts or redeploys, and it is not suitable for persistent hosted data. For persistence, use a PostgreSQL service and set `DATABASE_URL`. This prototype has no real banking integrations and is not intended to handle real financial data.

## Upload to another GitHub account

Create an empty repository while signed in to the **destination** GitHub account. From this `paran-bank` folder, initialize and push the project using that account's authenticated GitHub CLI or Git credentials:

```powershell
git init
git add .
git commit -m "Build Paran Bank prototype"
gh auth login
gh repo create YOUR-DESTINATION-ACCOUNT/paran-bank --private --source=. --remote=origin --push
```

Replace `YOUR-DESTINATION-ACCOUNT` with the destination account's username. Choose `--public` instead of `--private` only if you want the source publicly visible. If you already created the repository in GitHub, add its URL as `origin` and push the current branch:

```powershell
git remote add origin https://github.com/YOUR-DESTINATION-ACCOUNT/paran-bank.git
git branch -M main
git push -u origin main
```

Never add `.env` files, secrets, virtual environments, or local database files to Git. The included `.gitignore` excludes these items.
