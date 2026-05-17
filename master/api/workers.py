"""
Worker 管理 API（管理端，需要 JWT 认证）
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from master.database import (
    update_worker_status, get_worker, get_all_workers,
    remove_worker, reset_running_tasks_for_worker,
    get_worker_running_tasks, get_worker_running_count,
    update_worker_max_concurrent,
    get_worker_all_tasks, get_worker_task_counts
)

router = APIRouter(prefix="/api/workers", tags=["workers"])


class WorkerConfig(BaseModel):
    max_concurrent_tasks: int


@router.post("/{worker_id}/pause")
async def pause_worker(worker_id: str):
    """暂停 Worker：不再分发新任务"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    await update_worker_status(worker_id, 'paused')
    return {"success": True}


@router.post("/{worker_id}/resume")
async def resume_worker(worker_id: str):
    """恢复 Worker：重新接受任务分发"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    await update_worker_status(worker_id, 'active')
    return {"success": True}


@router.post("/{worker_id}/offline")
async def mark_offline(worker_id: str):
    """将 Worker 标记为离线，并重置其运行中的任务"""
    await update_worker_status(worker_id, 'offline')
    await reset_running_tasks_for_worker(worker_id)
    return {"success": True}


@router.delete("/{worker_id}")
async def delete_worker(worker_id: str):
    """删除 Worker"""
    await reset_running_tasks_for_worker(worker_id)
    await remove_worker(worker_id)
    return {"success": True}


@router.get("/list")
async def list_workers():
    """获取所有 Worker"""
    workers = await get_all_workers()
    return {"workers": workers}


@router.get("/{worker_id}/tasks")
async def worker_tasks(worker_id: str):
    """获取 Worker 当前正在执行的任务列表"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    tasks = await get_worker_running_tasks(worker_id)
    return {"tasks": tasks}


@router.get("/{worker_id}/stats")
async def worker_stats(worker_id: str):
    """获取 Worker 的任务统计"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    counts = await get_worker_task_counts(worker_id)
    return {"worker_id": worker_id, "counts": counts}


@router.get("/{worker_id}/all-tasks")
async def worker_all_tasks(worker_id: str, offset: int = 0, limit: int = 20, status: Optional[str] = None):
    """分页获取 Worker 的任务列表（包含所有状态）"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    tasks = await get_worker_all_tasks(worker_id, offset, limit, status)
    counts = await get_worker_task_counts(worker_id)
    return {"tasks": tasks, "total": counts.get('total', 0), "offset": offset, "limit": limit}


@router.get("/{worker_id}/status")
async def worker_status(worker_id: str):
    """获取 Worker 当前运行状态（并发数等）"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    active_count = await get_worker_running_count(worker_id)
    return {
        "worker": worker,
        "active_tasks": active_count,
        "max_concurrent": worker.get('max_concurrent_tasks', 1)
    }


@router.post("/{worker_id}/config")
async def update_config(worker_id: str, payload: WorkerConfig):
    """更新 Worker 并发配置"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if payload.max_concurrent_tasks < 1:
        raise HTTPException(status_code=400, detail="并发数不能小于 1")
    await update_worker_max_concurrent(worker_id, payload.max_concurrent_tasks)
    return {"success": True, "max_concurrent_tasks": payload.max_concurrent_tasks}
