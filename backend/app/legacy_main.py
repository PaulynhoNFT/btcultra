import asyncio
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.database import init_db, engine
from app.routes import auth, signals, backtest, market
from app.ingest import start_ingestor, stop_ingestor
from app.orchestrator import start_orchestrator, stop_orchestrator

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await start_orchestrator()
    ingest_task = asyncio.create_task(start_ingestor())
    try:
        yield
    finally:
        ingest_task.cancel()
        with suppress(asyncio.CancelledError):
            await ingest_task
        await stop_ingestor()
        await stop_orchestrator()
        await engine.dispose()


app = FastAPI(
    title="Signal Platform API",
    description="Triple Screen Crypto Signals — Charter 1.0",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth.router)
app.include_router(signals.router)
app.include_router(backtest.router)
app.include_router(market.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0", "engine": "triple-screen-v1"}


@app.get("/")
async def root():
    return {"message": "Signal Platform API", "docs": "/docs"}
