# Running UAT and production separately

Two isolated environments on the **same** GCP project (`fintrack-494214`) and
the **same** Cloud SQL instance (`fintrack-db`) — separate Cloud Run services,
separate databases, separate secrets, separate deploy triggers, separate EAS
channels.

| | production | UAT |
|---|---|---|
| Cloud Run service | `fintrack` | `fintrack-uat` |
| URL | `https://fintrack-989422306373.asia-south1.run.app` | `https://fintrack-uat-989422306373.asia-south1.run.app` *(set after first deploy)* |
| Database (on `fintrack-db`) | `fintrack` | `fintrack_uat` |
| DB user | `fintrack` | `fintrack_uat` |
| Secret Manager prefix | `fintrack-*` | `fintrack-uat-*` |
| Deploy trigger | `deploy-prod` — branch `^main$` | `deploy-uat` — branch `^uat$` |
| Frontend branch built into the image | `main` | `uat` |
| EAS channel / env | `production` | `preview` |
| Mobile build profile | `production` | `preview` |

Only one Cloud SQL instance is used, so the recurring cost stays ~one
`db-f1-micro`. Cloud Run scales to zero, so an idle UAT service costs ~nothing.

---

## Workflow

```
feature branch ──PR──▶ uat ──(deploy-uat fires)──▶ UAT env, test here
                        │
                        ▼ merge when happy
                       main ──(deploy-prod fires)──▶ production
```

- Backend push to `uat` → `deploy-uat` builds the image with the frontend's
  `uat` branch baked in, deploys to `fintrack-uat`.
- Merge `uat` → `main` → `deploy-prod` does the same for `fintrack`.
- Frontend-only change: push it to the frontend repo's `uat` / `main`, then
  re-run the matching backend trigger (the image bundles the web build):
  `gcloud builds triggers run deploy-uat --branch=uat --region=asia-south1`

Keep a `uat` branch on **both** repos.

---

## One-time: stand up UAT

All in Cloud Shell, project `fintrack-494214`, `REGION=asia-south1`.

### 1. UAT database + user on the existing instance

```bash
export UAT_DB_PASS="$(python3 -c 'import secrets,string;print("".join(secrets.choice(string.ascii_letters+string.digits) for _ in range(32)))')"
echo "$UAT_DB_PASS"        # save it

gcloud sql databases create fintrack_uat --instance=fintrack-db
gcloud sql users create fintrack_uat --instance=fintrack-db --password="$UAT_DB_PASS"
```

Give `fintrack_uat` ownership of its DB (so `create_all` can build the schema):

```bash
cloud-sql-proxy fintrack-494214:asia-south1:fintrack-db & sleep 5
PGPASSWORD='<postgres-user-pass>' psql -h 127.0.0.1 -U postgres -d fintrack_uat \
  -c "GRANT ALL ON DATABASE fintrack_uat TO fintrack_uat; ALTER DATABASE fintrack_uat OWNER TO fintrack_uat;"
```

(Optionally seed UAT with a copy of prod:
`pg_dump ".../fintrack" | psql ".../fintrack_uat"` between the two DBs on the proxy.)

### 2. UAT secrets (`fintrack-uat-*`)

Same 9 names as prod but prefixed. **Use fresh `secret-key` / `encryption-key`**
so a UAT token never works against prod. SMTP can be the same values.

```bash
export SQL_CONN=fintrack-494214:asia-south1:fintrack-db
mk() { printf '%s' "$2" | gcloud secrets create "$1" --replication-policy=automatic --data-file=- ; }

mk fintrack-uat-database-url        "postgresql://fintrack_uat:${UAT_DB_PASS}@/fintrack_uat?host=/cloudsql/${SQL_CONN}"
mk fintrack-uat-secret-key          "$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
mk fintrack-uat-encryption-key      "$(python3 -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
mk fintrack-uat-google-client-id    '989422306373-vjomjm06cfj8p4efvm98qp4acd6bsagg.apps.googleusercontent.com'
mk fintrack-uat-google-client-secret '<same GOOGLE_CLIENT_SECRET>'
mk fintrack-uat-smtp-user           '<smtp user>'
mk fintrack-uat-smtp-password       '<smtp app password>'
mk fintrack-uat-smtp-from           '<from address>'
mk fintrack-uat-admin-api-key       "$(python3 -c 'import secrets;print(secrets.token_hex(32))')"

PN=$(gcloud projects describe fintrack-494214 --format='value(projectNumber)')
for s in database-url secret-key encryption-key google-client-id google-client-secret smtp-user smtp-password smtp-from admin-api-key; do
  gcloud secrets add-iam-policy-binding "fintrack-uat-$s" \
    --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

### 3. First UAT deploy (gets its URL)

```bash
cd ~/fintrack-backend && git fetch && git checkout uat && git pull
gcloud builds submit --config cloudbuild.yaml --region=asia-south1 \
  --substitutions=_REGION=asia-south1,_SERVICE=fintrack-uat,_AR_REPO=cloud-run-source-deploy,_SQL_INSTANCE=fintrack-494214:asia-south1:fintrack-db,_SECRET_PREFIX=fintrack-uat,_FRONTEND_REF=uat,_APP_URL=https://PLACEHOLDER
```

It prints the service URL. Re-run once with the real `_APP_URL=https://fintrack-uat-989422306373.asia-south1.run.app` so `PUBLIC_BASE_URL` / `CORS_ORIGINS` and the baked-in web `apiUrl` are correct.

### 4. UAT deploy trigger

Console → Cloud Build → Triggers → **Create trigger** (same as `deploy-prod`):

- Name `deploy-uat`, repo `Akasht3010/fintrack-backend`, branch `^uat$`
- Config file `/cloudbuild.yaml`
- Substitutions:
  | var | value |
  |---|---|
  | `_REGION` | `asia-south1` |
  | `_SERVICE` | `fintrack-uat` |
  | `_AR_REPO` | `cloud-run-source-deploy` |
  | `_SQL_INSTANCE` | `fintrack-494214:asia-south1:fintrack-db` |
  | `_SECRET_PREFIX` | `fintrack-uat` |
  | `_APP_URL` | `https://fintrack-uat-989422306373.asia-south1.run.app` |
  | `_FRONTEND_REF` | `uat` |

The existing `deploy-prod` trigger just needs `_SECRET_PREFIX=fintrack` and
`_FRONTEND_REF=main` added to its substitutions (prod defaults already match).

### 5. OAuth — one Web client, both URLs

Google Cloud Console → Credentials → Web client `989422306373-…` → Authorized
redirect URIs, add:

```
https://fintrack-uat-989422306373.asia-south1.run.app/api/auth/google/callback
https://fintrack-uat-989422306373.asia-south1.run.app/api/gmail/callback
```

Each service's `PUBLIC_BASE_URL` differs, so each builds its own `redirect_uri`;
Google only needs both registered. Test users are per-consent-screen, shared.

---

## Mobile app: which backend a build talks to

`src/config/env.ts` reads **`EXPO_PUBLIC_API_URL`** first (inlined at bundle
time), then falls back to `app.json`'s `extra.apiUrl`.

Set it per **EAS environment** once:

```bash
cd fintrack
eas env:create --environment production --name EXPO_PUBLIC_API_URL --value https://fintrack-989422306373.asia-south1.run.app --visibility plaintext
eas env:create --environment preview    --name EXPO_PUBLIC_API_URL --value https://fintrack-uat-989422306373.asia-south1.run.app --visibility plaintext
```

`eas.json` maps `build.production` → environment `production` and
`build.preview` → environment `preview`, so:

| command | backend | reaches |
|---|---|---|
| `eas build --profile production` / `npm run update:production` | prod Cloud Run | store / `production`-channel builds |
| `eas build --profile preview` / `npm run update:preview` | UAT Cloud Run | internal APK / `preview`-channel builds |

Install the **preview** build alongside the production one to test UAT on a real
phone. Local dev: put `EXPO_PUBLIC_API_URL=http://<lan-ip>:8000` in a `.env`
file (git-ignored) or the shell instead of editing `app.json`.

---

## Day-to-day

```bash
# deploy prod
git checkout main && git merge uat && git push          # deploy-prod fires

# deploy uat
git checkout uat && git push                             # deploy-uat fires

# logs
gcloud run services logs tail fintrack-uat --region asia-south1

# psql into a specific env
cloud-sql-proxy fintrack-494214:asia-south1:fintrack-db &
PGPASSWORD=... psql -h 127.0.0.1 -U fintrack_uat -d fintrack_uat

# refresh UAT data from prod (destructive to UAT)
pg_dump  "postgresql://fintrack:$PROD_PASS@127.0.0.1:5432/fintrack" --clean --if-exists \
  | psql "postgresql://fintrack_uat:$UAT_PASS@127.0.0.1:5432/fintrack_uat"
```
