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
| Method | Path       | Auth required | Description |
|--------|------------|:---:|--------------|
| POST   | `/signup`  | – | Create an account with name, a real (unique) email, and a 10-digit phone. 409s if the email or phone is already registered. |
| POST   | `/login`   | – | Log in with a phone number **or** email via `{ identifier }`. 404s if no account matches. |
| GET    | `/me`      | ✅ | Get the authenticated user. |
| POST   | `/refresh` | ✅ | Issue a fresh access token for the authenticated user. |

### Google OAuth (`/api/auth/google`)
| Method | Path         | Description |
|--------|--------------|--------------|
| GET    | `/authorize` | Redirects to Google's consent screen. Takes `?app_redirect_uri=` — the client's own callback deep link — and threads it through as `state`. |
| GET    | `/callback`  | Google redirects here after consent (must match the redirect URI registered in Google Cloud Console). Exchanges the code, verifies the identity token, finds-or-creates the user by email, and redirects back to `state` with our own JWT as `?token=`. |

See **Google OAuth setup** below — this needs real credentials and, for local dev, a tunnel.

### Transactions (`/api/transactions`)
All routes require a bearer token; results/writes are scoped to the authenticated user (never trust a client-supplied `user_id`).

| Method | Path             | Description                          |
|--------|------------------|---------------------------------------|
| POST   | `/`              | Create a transaction owned by the authenticated user. |
| GET    | `/?page=&limit=` | Paginated list of the authenticated user's transactions, newest first. |
| GET    | `/{id}`          | Get a transaction — 404s if it doesn't belong to the authenticated user. |
| DELETE | `/{id}`          | Delete a transaction — 404s if it doesn't belong to the authenticated user. |

A transaction's `source` is one of `manual`, `gmail`, `sms`, or `aa` (account aggregator), tracking where it originated.

### Gmail (`/api/gmail`) — work in progress, not yet mounted in `main.py`
OAuth connect flow (`/auth-url`, `/connect`) and email sync (`/sync`, `/emails`) for auto-importing transactions from bank notification emails. Email parsing into transactions is still a TODO.

## Auth model

Auth is JWT-based (`HS256`, set `SECRET_KEY` in `.env`). The client stores the access token and sends it as `Authorization: Bearer <token>`; every protected route resolves the current user from that token via a `get_current_user` dependency (`app/utils/auth.py`) rather than trusting any client-supplied identifier.

Signup requires phone + email + name (all real, all unique). Login accepts either phone or email. Google sign-in is a third path into the *same* account space — it finds-or-creates a user by email and issues the same kind of JWT, so it's interchangeable with phone/email auth afterward.

## Google OAuth setup

Google requires the redirect URI in step 2 below to be `https://` (or `http://localhost`) — never a bare LAN IP — and Expo Go's own deep link changes every session, so a direct app-to-Google redirect doesn't work. Instead the backend mediates: the app opens `/api/auth/google/authorize`, Google redirects to this backend's fixed `/callback`, and the backend bounces the browser back to the app's current deep link with our own JWT attached.

To make this work locally:
1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), use (or create) a **Web application** OAuth client. Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env` to its values.
2. Expose this backend over HTTPS for local testing, e.g. with `ngrok http 8000`, and set `PUBLIC_BASE_URL` in `.env` to the ngrok URL it gives you.
3. In the same OAuth client, add `{PUBLIC_BASE_URL}/api/auth/google/callback` (using your actual ngrok URL) as an **Authorized redirect URI**.
4. Restart the backend so it picks up the new `.env` values.

Since free ngrok URLs change on every restart, you'll need to update step 3 each time you restart the tunnel — a paid ngrok static domain (or deploying the backend somewhere with a stable URL) avoids that.

## Notes

- Postgres data lives in a named Docker volume (`fintrack_pgdata`), not in the repo — each environment gets its own local database.
- `google-auth` (already a transitive dependency of `google-auth-oauthlib`) verifies Google's ID tokens; `google-auth-oauthlib`'s `Flow` handles the code exchange.
