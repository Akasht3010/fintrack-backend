import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config.database import Base, engine
from app.config.init_db import migrate_schema, seed_default_categories, encrypt_plaintext_gmail_tokens
from app.api import auth, transactions, budgets, google_auth, gmail, insights, recurring, categories, accounts, sms, admin
from app.web import mount_web

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 FastAPI starting up")
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    seed_default_categories()
    encrypt_plaintext_gmail_tokens()
    yield
    print("🛑 FastAPI shutting down")

app = FastAPI(
    title="Fintrack API",
    description="Unified expense tracking API",
    version="1.0.0",
    lifespan=lifespan
)

# The mobile app itself isn't subject to CORS (browsers enforce it, not RN's
# networking layer) — this only matters for browser-based clients (Expo web,
# the /docs Swagger UI making cross-origin calls, or any future web
# frontend). Origins must be listed explicitly since allow_origins=["*"]
# combined with allow_credentials=True is both rejected by browsers and,
# were it accepted, would let any website make credentialed requests using
# a logged-in user's browser session.
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(budgets.router)
app.include_router(google_auth.router)
app.include_router(gmail.router)
app.include_router(insights.router)
app.include_router(recurring.router)
app.include_router(categories.router)
app.include_router(accounts.router)
app.include_router(sms.router)
app.include_router(admin.router)

@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    # HEAD too: uptime monitors (UptimeRobot etc.) default to HEAD checks to
    # avoid pulling a response body just to confirm liveness.
    return {"status": "ok", "version": "1.0.0"}

# Static web build last, so every /api route and /health/docs win the match.
mount_web(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
