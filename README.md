# FinTrack Backend

FastAPI backend for [FinTrack](https://github.com/Akasht3010/fintrack) — a unified personal expense tracker. Handles auth, transactions, budgets, accounts, categories, spending insights, and recurring-bill detection, plus transaction ingestion from Gmail bank alerts and Android SMS.

## Tech stack

- **FastAPI** + **Uvicorn** — API server
- **PostgreSQL** + **SQLAlchemy 2** — database / ORM (SQLite is used only by the test suite)
- **Pydantic v2** + **pydantic-settings** — request/response validation
- **PyJWT** (`HS256`) + **bcrypt** — access/pending tokens and password hashing
- **Emailed OTP** (SMTP) — second factor on login and password reset
- **cryptography** (Fernet) — encrypts Gmail refresh tokens at rest
- **google-auth-oauthlib** / **google-api-python-client** — Google sign-in + Gmail OAuth and inbox reads
- **Celery** + **Redis** — background jobs (wired in, not yet used)

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
                        # (Postgres on host port 5433)

python run.py
```

`run.py` binds `$PORT` (falling back to 8000) and enables autoreload unless `ENV=production`.

On startup the app runs `Base.metadata.create_all` followed by `migrate_schema()` — a small hand-rolled shim in `app/config/init_db.py` that `ALTER TABLE`s in columns/indexes `create_all` can't add to existing tables (there's no Alembic yet) — then seeds the built-in categories and encrypts any still-plaintext Gmail tokens.

The API runs at `http://localhost:8000` (also reachable on your LAN IP, useful for testing from a physical device). Interactive docs live at `/docs`.

`docker compose up -d` also starts pgAdmin at `http://localhost:5050` (login `admin@fintrack.app` / `fintrack`). To reach the DB from a shell: `docker exec -it fintrack-backend-db-1 psql -U fintrack -d fintrack`.

### Tests

```bash
pip install -r requirements.txt   # pytest is included
pytest
```

The suite (`tests/`) runs entirely against an in-memory SQLite DB — no Postgres or network needed.

## Project structure

```
app/
  api/            # route handlers — auth, google_auth, transactions, budgets,
                  #   categories, accounts, insights, recurring, gmail, sms, admin
  models/         # SQLAlchemy models — User, Transaction, Budget, Account,
                  #   Category, OtpCode
  schemas/        # Pydantic request/response schemas
  services/       # business logic — user, budget, account, category, otp,
                  #   recurring detection, categorizer, email_parser,
                  #   email_service (SMTP), gmail_service, admin
  utils/          # JWT + OTP token helpers, Fernet crypto, OAuth-state nonces,
                  #   admin-key guard, IST timezone helpers
  config/         # DB session, app config, startup migrate/seed
sql/              # ad-hoc SQL — readable pgAdmin views, the int-id reset script
tests/            # pytest suite (in-memory SQLite)
run.py            # entrypoint (uvicorn)
```

## API overview

All `/api/*` routers are mounted in `app/main.py`. Every route below except signup, login step 1, forgot-password, and the OAuth redirect endpoints requires `Authorization: Bearer <access token>`; all reads/writes are scoped to the token's user (a client-supplied `user_id` is never trusted). `/health` (GET + HEAD) is public.

### Auth (`/api/auth`)

Login and password reset are two-step: password (or identity) check → emailed 6-digit OTP → token. Step 1 returns a short-lived `pending_token`; only step 2 issues a real access token.

| Method | Path               | Auth | Description |
|--------|--------------------|:---:|--------------|
| POST   | `/signup`          | – | Create an account: `name`, a real unique `email`, a 10-digit `phone`, `password` + `confirm_password` (8–72 chars). Returns an access token immediately (no OTP on signup). 409s if the email or phone is taken. |
| POST   | `/login`           | – | Step 1: `{ identifier (phone or email), password }`. Verifies the password, emails an OTP, returns `{ pending_token, email_hint }`. 404 unknown identifier, 401 wrong password, 400 if the account is Google-only. |
| POST   | `/verify-otp`      | – | Step 2: `{ pending_token, code }` → `{ access_token, user }`. |
| POST   | `/resend-otp`      | – | `{ pending_token }` — reissues the code for whichever flow (login or reset) the token was scoped to. Rate-limited by `OTP_RESEND_COOLDOWN_SECONDS`. |
| POST   | `/forgot-password` | – | Step 1 of reset: `{ identifier }` → emails an OTP, returns `{ pending_token, email_hint }`. Works for Google-only accounts setting a password for the first time. |
| POST   | `/reset-password`  | – | Step 2: `{ pending_token, code, new_password, confirm_new_password }` → sets the password and logs the user in (`{ access_token, user }`). |
| GET    | `/me`              | ✅ | The authenticated user. |
| PATCH  | `/me`              | ✅ | Update `name` / `email` / `phone`. Email and phone stay unique (409 otherwise). |
| DELETE | `/me`              | ✅ | Permanently delete the account and all its data (transactions, budgets, accounts, categories, OTPs). Best-effort revokes any Gmail grant first. Irreversible. |
| POST   | `/refresh`         | ✅ | Issue a fresh access token for the authenticated user. |

### Google OAuth (`/api/auth/google`)
| Method | Path         | Description |
|--------|--------------|--------------|
| GET    | `/authorize` | Redirects to Google's consent screen. Takes `?app_redirect_uri=` (the client's own callback deep link); it's bound server-side to a random nonce and only the nonce travels as `state`. |
| GET    | `/callback`  | Google redirects here after consent (must match the redirect URI registered in Google Cloud Console). Exchanges the code, verifies the ID token, finds-or-creates the user by email, and redirects back to the app's deep link with our own JWT as `?token=`. |

See **Google OAuth setup** below — this needs real credentials and, for local dev, a tunnel.

### Transactions (`/api/transactions`)

| Method | Path         | Description |
|--------|--------------|--------------|
| POST   | `/`          | Create a transaction (amounts are INR). `source` is forced to `manual` server-side (the gmail/sms paths build rows directly). `category` must exist; `account_id`, if given, must be owned. 409 on a duplicate `raw_text`. |
| GET    | `/`          | Paginated list (`page`, `limit≤100`), newest first. Filters: `category`, `q` (merchant/description search), `date_from`, `date_to`, `min_amount`, `max_amount`. |
| GET    | `/export`    | Same filters (plus `source`, `type`) → streamed CSV download. String cells are guarded against spreadsheet formula injection. |
| GET    | `/{id}`      | Get a transaction — 404 if not the caller's. |
| PATCH  | `/{id}`      | Update `amount` / `type` / `category` / `merchant` / `description` / `account_id`. |
| DELETE | `/{id}`      | Delete a transaction — 404 if not the caller's. |

`source` is one of `manual`, `gmail`, `sms`, `aa` (account aggregator). Imported rows carry a per-source dedup marker in `raw_text` (`gmail:<id>`, `sms:<address>:<epoch>`), enforced by a partial unique index on `(user_id, raw_text)`.

### Budgets (`/api/budgets`)
Per-category limits for the current week or month. `spent_amount` is a
materialized column: it's re-derived from the user's transactions (debits in
that category, within the budget window) and written back
whenever those transactions change — on transaction create / edit / delete
and after a Gmail or SMS sync — and re-checked on every `GET /api/budgets`,
so the stored row always equals what the app shows. `remaining_amount`
(`limit_amount - spent_amount`) is a DB-generated column — Postgres keeps it
in step with no app involvement.

| Method | Path        | Description |
|--------|-------------|--------------|
| POST   | `/`         | `{ category, limit_amount, period: weekly\|monthly }`. Seeds `spent_amount` from spend already in the period. 409 if a same-category, same-period budget is already active. |
| GET    | `/`         | Budgets active right now (`start_date <= now <= end_date`), each with current spend. |
| PATCH  | `/{id}`     | Change `limit_amount`. |
| DELETE | `/{id}`     | Delete a budget. |

### Categories (`/api/categories`)
Built-in defaults (`user_id IS NULL`, shared) plus the caller's own custom ones. Each has a `type` of `expense`, `income`, or `both` (transfer/other).

| Method | Path        | Description |
|--------|-------------|--------------|
| GET    | `/`         | Visible categories. `?type=expense` / `income` narrows to that type plus `both`. |
| POST   | `/`         | Create a custom category (`name`, `icon`, `type`). 409 on name collision. |
| PATCH  | `/{id}`     | Rename / re-icon / retype a custom category (defaults 404). A rename cascades onto existing transactions and budgets. |
| DELETE | `/{id}`     | Delete a custom category. 409 if any transaction or budget still references it. |

### Accounts (`/api/accounts`)
Bank / cash / credit-card / wallet / investment accounts. `balance` is `opening_balance` plus the sum of linked transactions, computed on read.

| Method | Path          | Description |
|--------|---------------|--------------|
| GET    | `/`           | The caller's accounts (active only unless `?include_archived=true`), with live balances. |
| GET    | `/net-worth`  | Assets minus credit-card balances owed, plus a per-account breakdown. |
| POST   | `/`           | Create an account (`name`, `type`, `opening_balance`). |
| PATCH  | `/{id}`       | Rename, correct the opening balance, or archive/unarchive. |
| DELETE | `/{id}`       | Delete — 409 if transactions still reference it (archive instead). |

### Insights (`/api/insights`)
`GET /` → monthly debit and credit totals over the last `months` (1–12, default 6), this month's category breakdown, and top merchants. All amounts are INR. `category = 'transfer'` rows (NEFT/IMPS/RTGS/fund transfers — money moved between accounts, a debit on one side and a credit on the other) are excluded from every figure here; recurring-bill detection skips them too. The parser tags bank transfers automatically; UPI-to-a-person is left as a normal expense.

### Recurring (`/api/recurring`)
`GET /` → subscriptions/bills inferred from spacing and amount consistency across past transactions, each with a cadence, average amount, and next-due date, plus a combined monthly-equivalent total.

### Gmail (`/api/gmail`)
Bank-alert email import. Refresh tokens are stored Fernet-encrypted.

| Method | Path          | Description |
|--------|---------------|--------------|
| GET    | `/authorize`  | Starts Gmail's OAuth consent (readonly scope). Takes `?token=` (the user's access token) and `?app_redirect_uri=`, both bound to a server-side nonce. |
| GET    | `/callback`   | Google redirects here; exchanges the code, stores the refresh token, bounces back to the app with `?gmail_connected=true`. |
| POST   | `/disconnect` | Best-effort revoke with Google, then clear the stored token. |
| POST   | `/sync`       | Fetch bank-alert emails, parse what it can (`email_parser`), auto-categorize (`categorizer`), and insert transactions. A stale (`invalid_grant`) token clears the connection and 401s. |

The search is restricted to bank-alert phrasing (`"debited from"`, `"credited to"`, `"transaction alert"`, …) — not merchant / UPI-app receipts, which describe the same purchase the bank already alerted on. `email_parser` additionally drops failed-payment notices and statement / credit-card-bill emails (an "amount due" isn't a transaction). Finally, the sync collapses anything with the **same amount within a 10-minute window** (any source) to one row, so the handful of emails one purchase generates don't each become a transaction.

### SMS (`/api/sms`)
`POST /sync` — the Android app reads bank-alert SMS from the device inbox and posts them here as `{ messages: [{ address, body, date }] }`; the backend has no SMS access of its own. Parsed with the same `email_parser` (Indian bank SMS and email alerts phrase things near-identically) and the same 10-minute same-amount dedup as the Gmail sync — so an SMS and its matching email collapse to one row. Returns `{ imported, skipped_duplicate, skipped_unparsed }`.

### Admin (`/api/admin`) — for [fintrack-monitor](../fintrack-monitor)
Every route requires an `X-Admin-Key` header matching `ADMIN_API_KEY` (routes disabled if that env var is unset). Aggregate figures only — never per-user detail.

| Method | Path       | Description |
|--------|------------|--------------|
| GET    | `/health`  | Process uptime, a live DB ping + latency, DB size, and an SMTP dependency check. |
| GET    | `/stats`   | User / transaction / account / budget counts, source breakdown, OTP funnel, stale-Gmail count, top categories, and 14-day signup & transaction series. |

## Auth model

Auth is JWT-based (`HS256`, set `SECRET_KEY` in `.env`). Two token kinds, both from `app/utils/auth.py`:

- **Access token** — issued on successful auth, expires after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30). The client stores it and sends it as `Authorization: Bearer <token>`; every protected route resolves the user via the `get_current_user` dependency rather than trusting any client-supplied id. There's no refresh-token flow — `/api/auth/refresh` mints a new one while the current is still valid, otherwise the session ends and the app returns to login.
- **Pending token** — short-lived, scoped to `login` or `password_reset`, carries no authority on its own. It only names which user is mid-OTP between step 1 and step 2, and protected routes reject it.

Password + emailed OTP is the default path: signup takes name + email + phone + password (all required, email and phone unique); login checks the password then emails a 6-digit code (`app/services/otp_service.py`, hashed in the `otp_codes` table with an attempt counter and expiry). Locally, with SMTP unset and `ENV=development`, the code is printed to the console instead of sent.

Google sign-in is a third path into the *same* account space — it finds-or-creates a user by email, skips OTP (Google already proved email ownership), and issues the same access token, so it's interchangeable with password auth afterward. A Google-only account has no `password_hash` until it runs the forgot-password flow to set one.

## Google OAuth setup

Google requires the redirect URI in step 2 below to be `https://` (or `http://localhost`) — never a bare LAN IP — and Expo Go's own deep link changes every session, so a direct app-to-Google redirect doesn't work. Instead the backend mediates: the app opens `/api/auth/google/authorize`, Google redirects to this backend's fixed `/callback`, and the backend bounces the browser back to the app's current deep link with our own JWT attached.

`PUBLIC_BASE_URL` is what `/authorize` and `/callback` build the Google
`redirect_uri` from (for both Google sign-in and Gmail connect). Google
redirects the **user's browser** straight to it, so it has to be a host that
browser can resolve — which is the crux of the production setup below.

### Local dev
1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), use (or create) a **Web application** OAuth client. Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env` to its values.
2. Expose this backend over HTTPS for local testing, e.g. with `ngrok http 8000`, and set `PUBLIC_BASE_URL` in `.env` to the ngrok URL it gives you.
3. In the same OAuth client, add both `{PUBLIC_BASE_URL}/api/auth/google/callback` and `{PUBLIC_BASE_URL}/api/gmail/callback` (using your actual ngrok URL) as **Authorized redirect URIs**, and add the ngrok domain under **Authorized domains** on the consent screen.
4. Restart the backend so it picks up the new `.env` values.

Since free ngrok URLs change on every restart, you'll need to redo step 3 each time you restart the tunnel — a paid ngrok static domain (or deploying somewhere with a stable URL) avoids that.

### Production

In production `PUBLIC_BASE_URL` is the app's one public origin — the Cloud Run
custom domain (`https://DOMAIN`). Google redirects the user's browser straight
to it after consent, so it has to be a host that resolves on any network; a
Cloud Run custom domain does (the old Railway `*.up.railway.app` didn't on some
carriers, which is why a Cloudflare proxy used to sit in front — that's gone).

On the Web OAuth client in Google Cloud Console:

- **Authorized redirect URIs** — `https://DOMAIN/api/auth/google/callback` and `https://DOMAIN/api/gmail/callback`
- **Authorized domains** (consent screen) — `DOMAIN`

See **[DEPLOY_GCP.md](DEPLOY_GCP.md)** for the full deploy.

The app side (`fintrack`) passes its own deep link as `app_redirect_uri`;
that must be the registered custom scheme (`fintrack://auth-callback`), not
Expo Go's `exp://<lan-ip>:8081/...` form, which is only routable on the dev
machine's Wi-Fi. See `makeRedirectUri({ scheme: "fintrack", ... })` in the
app's `useGoogleAuth` / `useGmailConnect` hooks.

## Notes

- Postgres data lives in a named Docker volume (`fintrack_pgdata`), not in the repo — each environment gets its own local database.
- `google-auth` (already a transitive dependency of `google-auth-oauthlib`) verifies Google's ID tokens; `google-auth-oauthlib`'s `Flow` handles the code exchange.
- Business timestamps (`Transaction.date`, `created_at`, …) are stored as **naive IST**, truncated to whole seconds, regardless of source. `requirements.txt` bundles `tzdata` so `zoneinfo` resolves `Asia/Kolkata` on any host.
- The app is INR-only. `Transaction.currency` / `Account.currency` still exist on the rows (always `"INR"`) so historical data stays valid, but there's no FX conversion anywhere — every total is a plain sum.
- **Deploy:** one **Cloud Run** service (`Dockerfile`) serves both the API and the Expo web export (`app/web.py` mounts `./web`, the build the deploy step drops in), backed by **Cloud SQL** Postgres, with config in **Secret Manager** and CI via `cloudbuild.yaml`. Full runbook in **[DEPLOY_GCP.md](DEPLOY_GCP.md)**.
