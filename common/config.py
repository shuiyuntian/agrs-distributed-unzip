"""
共享配置文件
"""

import os

# Master 服务配置
MASTER_HOST = os.environ.get("MASTER_HOST", "0.0.0.0")
MASTER_PORT = int(os.environ.get("MASTER_PORT", "8000"))
MASTER_URL = os.environ.get("MASTER_URL", f"http://localhost:{MASTER_PORT}")

# 数据库配置
DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data/distributed_unzip.db")

# NAS 路径配置（统一使用 UNC 路径，如 \\server\share\path）
NAS_INPUT_ROOT = os.environ.get("NAS_INPUT_ROOT", r"\\192.168.1.10\home\Drive\WorkSpace\06LAB\ray_unzip\data\tar_gz")
NAS_OUTPUT_ROOT = os.environ.get("NAS_OUTPUT_ROOT", r"\\192.168.1.10\home\Drive\WorkSpace\06LAB\ray_unzip\data\un_tar")

# 调度器配置
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "5"))      # Worker 心跳间隔（秒）
WORKER_TIMEOUT = int(os.environ.get("WORKER_TIMEOUT", "30"))              # Worker 超时判定（秒）
MAX_RETRY = int(os.environ.get("MAX_RETRY", "3"))                         # 单任务最大重试次数
SCHEDULER_INTERVAL = int(os.environ.get("SCHEDULER_INTERVAL", "10"))      # 调度器轮询间隔（秒）
PROGRESS_INTERVAL = int(os.environ.get("PROGRESS_INTERVAL", "2"))         # 进度上报间隔（秒）

# 解压引擎配置
USE_7Z_FALLBACK = os.environ.get("USE_7Z_FALLBACK", "false").lower() == "true"
SEVEN_ZIP_PATH = os.environ.get("SEVEN_ZIP_PATH", r"C:\Program Files\7-Zip\7z.exe")

# 日志配置
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
