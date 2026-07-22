from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config.database import Base, engine
from app.models.user import User
from app.models.transaction import Transaction
from app.models.budget import Budget
from app.api import auth, transactions, budgets, google_auth, gmail, insights

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 FastAPI starting up")
    Base.metadata.create_all(bind=engine)
    yield
    print("🛑 FastAPI shutting down")

app = FastAPI(
    title="Fintrack API",
    description="Unified expense tracking API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
