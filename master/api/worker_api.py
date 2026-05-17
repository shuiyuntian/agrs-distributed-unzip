"""
Worker-facing API (no auth required)
这些端点供 Worker 节点调用，通过 worker_id 进行身份验证
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from typing import Optional

from master.database import (
    get_worker, register_worker, update_worker_heartbeat,
    get_task, update_task_status, dispatch_task_atomic, set_worker_task,
    update_batch_status, increment_worker_tasks,
    get_worker_running_count
)

router = APIRouter(tags=["worker-api"])


class WorkerRegister(BaseModel):
    worker_id: str
    hostname: str
    ip_address: str
    max_concurrent_tasks: Optional[int] = 1


class WorkerHeartbeat(BaseModel):
    active_task_id: Optional[int] = None


@router.post("/api/workers/register")
async def worker_register(payload: WorkerRegister):
    """Worker 注册"""
    max_concurrent = payload.max_concurrent_tasks or 1
    if max_concurrent < 1:
        max_concurrent = 1
    await register_worker(payload.worker_id, payload.hostname, payload.ip_address, max_concurrent)
    return {"success": True, "worker_id": payload.worker_id}


@router.post("/api/workers/{worker_id}/heartbeat")
async def worker_heartbeat(worker_id: str, payload: WorkerHeartbeat):
    """Worker 心跳，返回当前状态"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found, please re-register")
    await update_worker_heartbeat(worker_id, payload.active_task_id)
    return {"success": True, "status": worker['status']}


@router.get("/api/tasks/poll")
async def poll_task(worker_id: str):
    """Worker 拉取待处理任务（原子分发，避免竞争条件）"""
    worker = await get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=403, detail="Worker not registered")
    if worker['status'] == 'paused':
        return Response(status_code=204)
    if worker['status'] != 'active':
        raise HTTPException(status_code=403, detail="Worker not active")

    # 检查并发限制
    active_count = await get_worker_running_count(worker_id)
    max_concurrent = worker.get('max_concurrent_tasks', 1)
    if active_count >= max_concurrent:
        return Response(status_code=204)

    task = await dispatch_task_atomic(worker_id)
    if not task:
        return Response(status_code=204)

    await set_worker_task(worker_id, task['id'])
    if task.get('batch_id'):
        await update_batch_status(task['batch_id'])
    return task


@router.post("/api/tasks/{task_id}/progress")
async def update_progress(task_id: int, worker_id: str, processed_bytes: int, processed_files: int, speed_mbps: float):
    """Worker 上报任务进度"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] != 'running':
        raise HTTPException(status_code=409, detail="Task is not running")
    if task['worker_id'] != worker_id:
        raise HTTPException(status_code=403, detail="Task not assigned to this worker")
    await update_task_status(
        task_id, 'running', worker_id=worker_id,
        processed_bytes=processed_bytes, processed_files=processed_files, speed_mbps=speed_mbps
    )
    return {"success": True}


@router.post("/api/tasks/{task_id}/complete")
async def complete_task(task_id: int, worker_id: str):
    """Worker 上报任务完成"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] == 'cancelled':
        raise HTTPException(status_code=409, detail="Task has been cancelled")
    if task['status'] != 'running':
        raise HTTPException(status_code=409, detail="Task is not running")
    if task['worker_id'] != worker_id:
        raise HTTPException(status_code=403, detail="Task not assigned to this worker")
    await update_task_status(task_id, 'success', worker_id=worker_id)
    from master.database import increment_worker_tasks
    await increment_worker_tasks(worker_id)
    # 多任务并发时，只清除当前任务的 active_task_id
    if task.get('batch_id'):
        await update_batch_status(task['batch_id'])
    return {"success": True}


@router.post("/api/tasks/{task_id}/fail")
async def fail_task(task_id: int, worker_id: str, error: str):
    """Worker 上报任务失败"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] == 'cancelled':
        raise HTTPException(status_code=409, detail="Task has been cancelled")
    if task['status'] != 'running':
        raise HTTPException(status_code=409, detail="Task is not running")
    if task['worker_id'] != worker_id:
        raise HTTPException(status_code=403, detail="Task not assigned to this worker")
    from master.database import increment_retry_count
    will_retry = await increment_retry_count(task_id)
    if will_retry:
        await update_task_status(task_id, 'retrying', worker_id=None, error_message=error)
    else:
        await update_task_status(task_id, 'failed', worker_id=None, error_message=error)
    if task.get('batch_id'):
        await update_batch_status(task['batch_id'])
    return {"success": True, "will_retry": will_retry}
