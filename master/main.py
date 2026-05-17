"""
Master 主程序入口
"""

import os
os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")

import sys

# PyInstaller EXE mode: use exe directory for persistent data storage
if hasattr(sys, '_MEIPASS'):
    exe_dir = os.path.dirname(sys.executable)
    os.environ.setdefault("DATABASE_PATH", os.path.join(exe_dir, "data", "distributed_unzip.db"))

import asyncio
import logging
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from master.database import init_db, close_db
from master.scheduler import scheduler_loop
from master.api import tasks, workers, stats, auth, users, worker_api
from master.api.auth import get_current_user
from common.config import MASTER_HOST, MASTER_PORT, LOG_LEVEL, LOG_FORMAT

logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)
logger = logging.getLogger("master")

_scheduler_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db()
    
    logger.info("Starting scheduler...")
    global _scheduler_task
    _scheduler_task = asyncio.create_task(scheduler_loop())
    
    yield
    
    logger.info("Shutting down...")
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    await close_db()


app = FastAPI(
    title="Distributed Unzip",
    description="Distributed decompression system",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public APIs (no auth required)
app.include_router(auth.router)
app.include_router(worker_api.router)

# Protected APIs (JWT required)
app.include_router(tasks.router, dependencies=[Depends(get_current_user)])
app.include_router(workers.router, dependencies=[Depends(get_current_user)])
app.include_router(stats.router, dependencies=[Depends(get_current_user)])
app.include_router(users.router, dependencies=[Depends(get_current_user)])

# Static files
def get_static_dir():
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, "master", "static")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

static_dir = get_static_dir()
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "login.html"))


@app.get("/login")
async def login_page():
    return FileResponse(os.path.join(static_dir, "login.html"))


@app.get("/submit")
async def submit_page():
    return FileResponse(os.path.join(static_dir, "submit.html"))


@app.get("/tasks")
async def tasks_page():
    return FileResponse(os.path.join(static_dir, "tasks.html"))


@app.get("/workers")
async def workers_page():
    return FileResponse(os.path.join(static_dir, "workers.html"))


@app.get("/users")
async def users_page():
    return FileResponse(os.path.join(static_dir, "users.html"))


@app.get("/dashboard")
async def dashboard():
    return FileResponse(os.path.join(static_dir, "dashboard.html"))


@app.get("/worker")
async def worker_detail_page():
    return FileResponse(os.path.join(static_dir, "worker_detail.html"))


@app.get("/batch")
async def batch_detail_page():
    return FileResponse(os.path.join(static_dir, "batch_detail.html"))


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    # Interactive port input when launched by double-click (no extra CLI args)
    port = MASTER_PORT
    if len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty():
        try:
            user_port = input(f"请输入 Master 服务端口号 (默认 {MASTER_PORT}): ").strip()
            if user_port:
                port = int(user_port)
        except (ValueError, EOFError):
            pass
    
    uvicorn.run(app, host=MASTER_HOST, port=port)
