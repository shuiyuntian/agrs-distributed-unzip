"""
Master 后台调度器
负责：Worker 超时检测、任务重试、定期统计
"""

import asyncio
import logging
from datetime import datetime, timedelta
from master.database import (
    get_db, get_all_workers, update_worker_status, reset_running_tasks_for_worker,
    get_task_counts, record_stats
)
from common.config import WORKER_TIMEOUT, SCHEDULER_INTERVAL

logger = logging.getLogger("scheduler")


async def check_worker_timeout():
    """检测 Worker 心跳超时，将超时的 Worker 标记为 offline，并释放其任务"""
    workers = await get_all_workers()
    # SQLite CURRENT_TIMESTAMP 返回 UTC 时间，所以用 utcnow() 比较
    timeout_threshold = datetime.utcnow() - timedelta(seconds=WORKER_TIMEOUT)
    
    for worker in workers:
        last_heartbeat = worker.get('last_heartbeat')
        if last_heartbeat:
            if isinstance(last_heartbeat, str):
                # 数据库中的时间没有时区信息，按 UTC 解析
                last_heartbeat = datetime.fromisoformat(last_heartbeat)
            if last_heartbeat < timeout_threshold and worker['status'] == 'active':
                logger.warning(f"Worker {worker['id']} ({worker['hostname']}) heartbeat timeout, marking offline")
                await update_worker_status(worker['id'], 'offline')
                await reset_running_tasks_for_worker(worker['id'])


async def scheduler_loop():
    """调度器主循环"""
    logger.info("Scheduler started")
    while True:
        try:
            await check_worker_timeout()
            await record_stats()
        except Exception as e:
            logger.exception(f"Scheduler error: {e}")
        
        await asyncio.sleep(SCHEDULER_INTERVAL)
