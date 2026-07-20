# FinTrack Backend

FastAPI backend for [FinTrack](https://github.com/Akasht3010/fintrack) — a unified personal expense tracker. Handles auth, transactions, and budgets, with a Gmail-based transaction ingestion service in progress.

## Tech stack

- **FastAPI** + **Uvicorn** — API server
- **PostgreSQL** + **SQLAlchemy** — database / ORM
- **Pydantic v2** — request/response validation
- **Celery** + **Redis** — background jobs (wired in, not yet used)
- **google-api-python-client** — Gmail OAuth + email ingestion

## Getting started

```bash
# 1. Start Postgres (local dev instance, via Docker)
docker compose up -d

# 2. Python env
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in SECRET_KEY, Google OAuth creds, etc.
                        # DATABASE_URL already matches the docker-compose defaults

python run.py
```

Tables are created automatically on startup (`Base.metadata.create_all`) — no separate migration step needed yet.

The API runs at `http://localhost:8000` (also reachable on your LAN IP, useful for testing from a physical device). Interactive docs live at `/docs`.

To connect to the local DB directly: `docker exec -it fintrack-backend-db-1 psql -U fintrack -d fintrack`

## Project structure

```
app/
  api/            # route handlers (auth, transactions, gmail)
  models/         # SQLAlchemy models (User, Transaction, Budget)
  schemas/        # Pydantic request/response schemas
  services/       # business logic (user lookups, Gmail sync)
  utils/          # JWT auth helpers
  config/         # DB session + app config
run.py            # entrypoint (uvicorn)
```

## API overview

### Auth (`/api/auth`)
| Method | Path      | Description                                      |
|--------|-----------|---------------------------------------------------|
| POST   | `/signup` | Create an account with a name + phone and/or email. Idempotent — returns the existing account if the phone/email is already registered. |
| POST   | `/login`  | Log in with a phone number **or** email via `{ identifier }`. 404s if no account matches. |
| GET    | `/me`     | Get the current user by `user_id`. |
| POST   | `/refresh`| Issue a fresh access token for a `user_id`. |

### Transactions (`/api/transactions`)
| Method | Path                | Description                          |
|--------|---------------------|---------------------------------------|
| POST   | `/`                 | Create a transaction. |
| GET    | `/?user_id=&page=&limit=` | Paginated list of a user's transactions, newest first. |
| GET    | `/{id}`             | Get a single transaction. |
| DELETE | `/{id}`             | Delete a transaction. |

A transaction's `source` is one of `manual`, `gmail`, `sms`, or `aa` (account aggregator), tracking where it originated.

### Gmail (`/api/gmail`) — work in progress, not yet mounted in `main.py`
OAuth connect flow (`/auth-url`, `/connect`) and email sync (`/sync`, `/emails`) for auto-importing transactions from bank notification emails. Email parsing into transactions is still a TODO.

## Auth model

Auth is JWT-based (`HS256`, set `SECRET_KEY` in `.env`). There's no session/cookie state — the client stores the access token and sends it as a bearer token. Users can be looked up by phone or email; both are optional individually but at least one is required to sign up.

## Notes

- Postgres data lives in a named Docker volume (`fintrack_pgdata`), not in the repo — each environment gets its own local database.
- Google OAuth credentials in `.env` are currently placeholders; the Gmail sync flow needs real credentials to test end-to-end.
- Next planned step: Google OAuth login on the frontend, replacing/augmenting phone+email auth.
