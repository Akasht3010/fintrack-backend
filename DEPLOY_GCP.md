# Deploying FinTrack on GCP

One **Cloud Run** service runs the whole app — FastAPI on `/api/*`, `/health`,
`/docs`, and the Expo web export on everything else — backed by **Cloud SQL**
for PostgreSQL, with secrets in **Secret Manager** and builds through
**Cloud Build**.

This replaced the old split (backend on Railway, web on a Cloudflare Worker,
the `fintrack-api-proxy` Worker). The mobile app stays on **EAS** — GCP doesn't
distribute mobile apps.

## Live deployment

| | value |
|---|---|
| Project | `fintrack-494214` |
| Region | `asia-south1` |
| Cloud Run service | `fintrack` → **https://fintrack-989422306373.asia-south1.run.app** |
| Cloud SQL | `fintrack-494214:asia-south1:fintrack-db` (POSTGRES_18, `db-f1-micro`), db `fintrack`, user `fintrack` |
| Artifact Registry | `asia-south1-docker.pkg.dev/fintrack-494214/cloud-run-source-deploy` |
| Deploy | Cloud Build trigger `deploy-main` on `fintrack-backend` `main`. Frontend changes: `gcloud builds triggers run deploy-main --branch=main --region=asia-south1`. |
| OAuth | Web client `989422306373-…`, redirect URIs at `…run.app/api/auth/google/callback` + `/api/gmail/callback` |

The rest of this doc is the from-scratch runbook (placeholders below).

Fill in these throughout:

| placeholder | example | notes |
|---|---|---|
| `PROJECT_ID` | `fintrack-prod` | GCP project id |
| `REGION` | `asia-south1` | Mumbai; pick one near your users |
| `DOMAIN` | `fintrack.example.com` | a domain **you own** — becomes the one public origin |
| `DB_PASS` | *(generate)* | Cloud SQL app-user password |

```bash
gcloud auth login
```

---

## 1. Project, billing, APIs

```bash
gcloud projects create PROJECT_ID
gcloud config set project PROJECT_ID
# link billing (get the id from: gcloud billing accounts list)
gcloud billing projects link PROJECT_ID --billing-account=XXXXXX-XXXXXX-XXXXXX

gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

## 2. Artifact Registry (image repo)

```bash
gcloud artifacts repositories create fintrack \
  --repository-format=docker --location=REGION \
  --description="FinTrack images"
```

## 3. Cloud SQL for PostgreSQL

`db-f1-micro` is the cheapest tier (shared vCPU, ~$8–10/mo, always on — Cloud SQL
does not scale to zero).

```bash
gcloud sql instances create fintrack-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=REGION \
  --storage-auto-increase \
  --backup-start-time=19:30            # 01:00 IST

gcloud sql databases create fintrack --instance=fintrack-db
gcloud sql users create fintrack --instance=fintrack-db --password='DB_PASS'
```

Connection name (you'll need it a few times):

```bash
gcloud sql instances describe fintrack-db --format='value(connectionName)'
# -> PROJECT_ID:REGION:fintrack-db
```

`DATABASE_URL` for Cloud Run (unix socket, no VPC needed):

```
postgresql://fintrack:DB_PASS@/fintrack?host=/cloudsql/PROJECT_ID:REGION:fintrack-db
```

## 4. Move the data off Railway

```bash
# dump from Railway (grab DATABASE_URL from the Railway service → Variables)
pg_dump --no-owner --no-privileges --format=plain \
  "postgresql://USER:PASS@HOST:PORT/railway" > fintrack_dump.sql

# open a local tunnel to Cloud SQL
gcloud sql connect fintrack-db --user=fintrack --database=fintrack    # or:
cloud-sql-proxy PROJECT_ID:REGION:fintrack-db &                       # then psql to 127.0.0.1:5432

psql "postgresql://fintrack:DB_PASS@127.0.0.1:5432/fintrack" -f fintrack_dump.sql
```

The app also self-heals on boot (`create_all` + `migrate_schema` + category
seed), so a fresh empty DB is fine if you don't need the existing rows.

## 5. Secrets

```bash
mk() { printf '%s' "$2" | gcloud secrets create "$1" --data-file=- ; }

mk fintrack-database-url      'postgresql://fintrack:DB_PASS@/fintrack?host=/cloudsql/PROJECT_ID:REGION:fintrack-db'
mk fintrack-secret-key        "$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
mk fintrack-encryption-key    "$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
mk fintrack-google-client-id  'YOUR_GOOGLE_WEB_CLIENT_ID'
mk fintrack-google-client-secret 'YOUR_GOOGLE_WEB_CLIENT_SECRET'
mk fintrack-smtp-user         'you@gmail.com'
mk fintrack-smtp-password     'your-gmail-app-password'
mk fintrack-smtp-from         'you@gmail.com'
mk fintrack-admin-api-key     "$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
```

> Reuse the **existing** `SECRET_KEY` / `ENCRYPTION_KEY` from Railway if you're
> keeping the Railway data — regenerating them invalidates every session and
> makes stored Gmail tokens undecryptable.

Grant the Cloud Run runtime service account read access:

```bash
PN=$(gcloud projects describe PROJECT_ID --format='value(projectNumber)')
for s in database-url secret-key encryption-key google-client-id google-client-secret \
         smtp-user smtp-password smtp-from admin-api-key; do
  gcloud secrets add-iam-policy-binding "fintrack-$s" \
    --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

## 6. First deploy (manual)

Build the web export and drop it into `web/`, then let Cloud Run build from source:

```bash
# in the frontend repo
cd ../fintrack
# point the web build at the new origin (don't commit this if you keep a local LAN override)
npx json -I -f app.json -e 'this.expo.extra.apiUrl="https://DOMAIN"'   # or edit by hand
npx expo export -p web

# hand it to the backend
rm -rf ../fintrack-backend/web && cp -r dist ../fintrack-backend/web
cd ../fintrack-backend

gcloud run deploy fintrack \
  --source . \
  --region REGION \
  --allow-unauthenticated \
  --add-cloudsql-instances PROJECT_ID:REGION:fintrack-db \
  --port 8080 --cpu 1 --memory 512Mi --min-instances 0 --max-instances 4 \
  --set-env-vars ENV=production,ACCESS_TOKEN_EXPIRE_MINUTES=30,OTP_EXPIRE_MINUTES=5,OTP_RESEND_COOLDOWN_SECONDS=30,PUBLIC_BASE_URL=https://DOMAIN,CORS_ORIGINS=https://DOMAIN,SMTP_HOST=smtp.gmail.com,SMTP_PORT=587 \
  --set-secrets DATABASE_URL=fintrack-database-url:latest,SECRET_KEY=fintrack-secret-key:latest,ENCRYPTION_KEY=fintrack-encryption-key:latest,GOOGLE_CLIENT_ID=fintrack-google-client-id:latest,GOOGLE_CLIENT_SECRET=fintrack-google-client-secret:latest,SMTP_USER=fintrack-smtp-user:latest,SMTP_PASSWORD=fintrack-smtp-password:latest,SMTP_FROM=fintrack-smtp-from:latest,ADMIN_API_KEY=fintrack-admin-api-key:latest
```

Check the temporary URL it prints: `https://fintrack-xxxx-REGION.run.app/health`
and the web app at `/`.

## 7. Custom domain

```bash
gcloud beta run domain-mappings create --service fintrack --domain DOMAIN --region REGION
gcloud beta run domain-mappings describe --domain DOMAIN --region REGION   # shows the DNS records to add
```

Add the shown `A`/`AAAA` (or `CNAME` for a subdomain) records at your registrar.
The managed TLS cert provisions automatically once DNS resolves (minutes to an hour).
`*.run.app` already resolves everywhere, so the app works before the domain is live.

## 8. Google OAuth

In [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials),
on the **Web** OAuth client:

- **Authorized redirect URIs** — add:
  - `https://DOMAIN/api/auth/google/callback`
  - `https://DOMAIN/api/gmail/callback`
- **Authorized domains** (OAuth consent screen) — add `DOMAIN`

`PUBLIC_BASE_URL` is already `https://DOMAIN`, so the backend builds the right
`redirect_uri`. The Cloudflare proxy is no longer in the path — a Cloud Run
custom domain resolves on every network.

## 9. Frontend + mobile

- **Web** is served by Cloud Run now — nothing else to host.
- **Mobile**: set `extra.apiUrl` in `fintrack/app.json` to `https://DOMAIN`, commit,
  then push it to installed apps:
  ```bash
  cd ../fintrack
  npm run update:production
  ```
  (New native build only if you bump the runtime version.)

## 10. CI (deploy on push)

`cloudbuild.yaml` in this repo does steps 6 automatically. Create the trigger:

```bash
gcloud builds triggers create github \
  --repo-name=fintrack-backend --repo-owner=Akasht3010 \
  --branch-pattern='^main$' \
  --build-config=cloudbuild.yaml \
  --region=REGION \
  --substitutions=_REGION=REGION,_SERVICE=fintrack,_AR_REPO=fintrack,_SQL_INSTANCE=PROJECT_ID:REGION:fintrack-db,_APP_URL=https://DOMAIN
```

Grant the **Cloud Build** service account deploy rights:

```bash
PN=$(gcloud projects describe PROJECT_ID --format='value(projectNumber)')
for role in roles/run.admin roles/iam.serviceAccountUser roles/cloudsql.client; do
  gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:${PN}@cloudbuild.gserviceaccount.com" --role="$role"
done
```

Also add a trigger on the **frontend** repo (`fintrack`, `^main$`, same
`cloudbuild.yaml` path via `--repo-name=fintrack` won't work — instead point that
trigger at this repo's config too, or just redeploy the backend after a frontend
change). Simplest: one trigger here; run it manually after a frontend change with
`gcloud builds triggers run <name> --branch=main`.

## 11. Decommission

Once `https://DOMAIN` is verified working end to end (web, login+OTP, Google
sign-in, Gmail connect, a sync):

- Railway: delete the service and its Postgres add-on.
- Cloudflare: delete the `fintrack` Worker and the `fintrack-api-proxy` Worker.
  Keep `fintrack-web` (marketing) / `fintrack-monitor` or move them to Firebase
  Hosting later — they're independent.

## Day-to-day

```bash
# logs
gcloud run services logs tail fintrack --region REGION

# open a psql shell on prod
gcloud sql connect fintrack-db --user=fintrack --database=fintrack

# one-off SQL (e.g. sql/dedupe_imported_transactions.sql)
psql "postgresql://fintrack:DB_PASS@127.0.0.1:5432/fintrack" -f sql/whatever.sql   # via cloud-sql-proxy

# rotate a secret
printf '%s' NEW_VALUE | gcloud secrets versions add fintrack-secret-key --data-file=-
gcloud run services update fintrack --region REGION   # picks up :latest on next deploy/restart
```

Schema changes are applied by the app on boot (`Base.metadata.create_all` +
`migrate_schema()` in `app/config/init_db.py`) — no separate migration step.
