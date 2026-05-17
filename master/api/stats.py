"""
统计与 Dashboard API
"""

from fastapi import APIRouter
from master.database import (
    get_task_counts, get_batch_counts, get_all_workers, get_recent_stats, get_latest_stats, record_stats
)
from common.config import NAS_INPUT_ROOT, NAS_OUTPUT_ROOT

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/dashboard")
async def dashboard_stats():
    """Dashboard 核心数据"""
    batch_counts = await get_batch_counts()
    task_counts_data = await get_task_counts()
    workers = await get_all_workers()
    
    active_workers = [w for w in workers if w['status'] == 'active']
    busy_workers = [w for w in active_workers if w['active_task_id'] is not None]
    
    latest = await get_latest_stats()
    avg_speed = latest.get('avg_speed_mbps', 0) or 0
    throughput = latest.get('throughput_mbps', 0) or 0
    
    pending_count = batch_counts.get('pending', 0) + batch_counts.get('partial', 0)
    
    estimated_seconds = 0
    if throughput > 0 and pending_count > 0:
        avg_package_mb = 650
        estimated_seconds = (pending_count * avg_package_mb) / throughput
    
    return {
        "batches": {
            "total": batch_counts['total'],
            "pending": batch_counts.get('pending', 0),
            "running": batch_counts.get('running', 0),
            "success": batch_counts.get('success', 0),
            "failed": batch_counts.get('failed', 0),
            "partial": batch_counts.get('partial', 0)
        },
        "tasks": {
            "total": task_counts_data['total'],
            "pending": task_counts_data.get('pending', 0) + task_counts_data.get('retrying', 0),
            "running": task_counts_data.get('running', 0),
            "success": task_counts_data.get('success', 0),
            "failed": task_counts_data.get('failed', 0)
        },
        "workers": {
            "total": len(workers),
            "active": len(active_workers),
            "busy": len(busy_workers),
            "idle": len(active_workers) - len(busy_workers),
            "offline": len(workers) - len(active_workers)
        },
        "performance": {
            "throughput_mbps": round(throughput, 2),
            "avg_speed_mbps": round(avg_speed, 2),
            "estimated_seconds_remaining": int(estimated_seconds)
        },
        "paths": {
            "input_root": NAS_INPUT_ROOT,
            "output_root": NAS_OUTPUT_ROOT
        }
    }


@router.get("/history")
async def stats_history(minutes: int = 10):
    """获取历史统计数据用于图表"""
    history = await get_recent_stats(minutes)
    return {"history": history}


@router.post("/record")
async def trigger_record():
    """手动触发一次统计记录"""
    await record_stats()
    return {"success": True}
