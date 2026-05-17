"""
任务管理 API
"""

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from master.database import (
    get_db, create_task, get_task, update_task_status, get_all_tasks,
    get_task_counts, reset_running_tasks_for_worker,
    increment_retry_count, delete_tasks_by_status, set_worker_task,
    create_batch, get_batch, update_batch_status, set_batch_status, get_all_batches, get_batch_counts,
    get_tasks_by_batch, delete_batch, get_batch_task_counts
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskSubmit(BaseModel):
    input_paths: List[str]
    output_root: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    input_path: str
    output_path: str
    archive_type: Optional[str]
    status: str
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    worker_id: Optional[str]
    retry_count: int
    error_message: Optional[str]
    total_bytes: int
    processed_bytes: int
    processed_files: int
    total_files: int
    speed_mbps: float


def detect_archive_type(path: str) -> Optional[str]:
    """严格检测压缩包格式，只识别标准后缀"""
    path_lower = path.lower()
    if path_lower.endswith('.zip'):
        return 'zip'
    elif path_lower.endswith('.tar.gz') or path_lower.endswith('.tgz'):
        return 'tar.gz'
    elif path_lower.endswith('.tar'):
        return 'tar'
    elif path_lower.endswith('.gz'):
        return 'gz'
    return None


def get_base_name(path: str, archive_type: str) -> str:
    """从路径中提取去掉了扩展名的文件名"""
    name = os.path.basename(path)
    name_lower = name.lower()
    if archive_type == 'tar.gz':
        for suffix in ['.tar.gz', '.tgz']:
            if name_lower.endswith(suffix):
                return name[:-len(suffix)]
    elif archive_type == 'gz':
        if name_lower.endswith('.gz'):
            return name[:-3]
    else:
        base, _ = os.path.splitext(name)
        return base
    return name


def get_file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except:
        return 0


def scan_folder_recursive(folder_path: str) -> List[str]:
    """递归扫描文件夹及其子文件夹中的所有合法压缩包"""
    archives = []
    try:
        for root, dirs, files in os.walk(folder_path):
            for name in files:
                full_path = os.path.join(root, name)
                if detect_archive_type(full_path):
                    archives.append(full_path)
    except Exception:
        pass
    return archives


@router.post("/submit", response_model=List[int])
async def submit_tasks(payload: TaskSubmit):
    """提交解压任务，支持文件夹路径自动递归扫描"""
    batch_ids = []
    output_root = payload.output_root
    
    for input_path in payload.input_paths:
        input_path = input_path.strip()
        if not input_path:
            continue
        
        # 判断是文件夹还是文件
        if os.path.isdir(input_path):
            # 文件夹：递归扫描所有子文件夹中的合法压缩包
            archive_paths = scan_folder_recursive(input_path)
        elif os.path.isfile(input_path):
            archive_paths = [input_path]
        else:
            continue
        
        if not archive_paths:
            continue
        
        # 创建 batch（批次）
        batch_id = await create_batch(input_path, output_root)
        
        for archive_path in archive_paths:
            archive_type = detect_archive_type(archive_path)
            if not archive_type:
                continue
            
            base_name = get_base_name(archive_path, archive_type)
            
            if output_root:
                # 保持原始文件夹结构，在 output_root 下重建相对路径
                rel_path = os.path.relpath(os.path.dirname(archive_path), input_path) if os.path.isdir(input_path) else ''
                if rel_path == '.':
                    output_path = os.path.join(output_root, base_name)
                else:
                    output_path = os.path.join(output_root, rel_path, base_name)
            else:
                output_path = os.path.join(os.path.dirname(archive_path), base_name)
            
            total_bytes = get_file_size(archive_path)
            await create_task(batch_id, archive_path, output_path, archive_type, total_bytes, 0)
        
        # 更新 batch 的子任务数量
        await update_batch_status(batch_id)
        batch_ids.append(batch_id)
    
    return batch_ids


@router.get("/batches")
async def list_batches(offset: int = 0, limit: int = 100, status: Optional[str] = None):
    """获取批次（任务）列表"""
    batches = await get_all_batches(offset, limit, status)
    counts = await get_batch_counts()
    return {"batches": batches, "counts": counts}


@router.get("/batches/{batch_id}")
async def get_batch_detail(batch_id: int):
    """获取批次详情，包含子任务列表"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    tasks = await get_tasks_by_batch(batch_id)
    return {"batch": batch, "tasks": tasks}


@router.get("/batches/{batch_id}/stats")
async def batch_stats(batch_id: int):
    """获取批次的任务统计"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    counts = await get_batch_task_counts(batch_id)
    return {"batch_id": batch_id, "counts": counts}


@router.get("/batches/{batch_id}/all-tasks")
async def list_batch_all_tasks(batch_id: int, offset: int = 0, limit: int = 50, status: Optional[str] = None):
    """分页获取批次下的所有子任务（带筛选）"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    tasks = await get_all_tasks(offset, limit, status, batch_id)
    counts = await get_batch_task_counts(batch_id)
    return {"tasks": tasks, "total": counts.get('total', 0), "offset": offset, "limit": limit}


@router.get("/batches/{batch_id}/tasks")
async def list_batch_tasks(batch_id: int):
    """获取批次下的所有子任务（无分页，兼容旧接口）"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    tasks = await get_tasks_by_batch(batch_id)
    return {"tasks": tasks}


@router.delete("/batches/{batch_id}")
async def remove_batch(batch_id: int):
    """删除批次及其所有子任务"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    await delete_batch(batch_id)
    return {"success": True}


@router.post("/batches/{batch_id}/pause")
async def pause_batch(batch_id: int):
    """暂停批次：停止分发新任务，pending 子任务标记为 paused"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    await set_batch_status(batch_id, 'paused')
    db = await get_db()
    await db.execute(
        "UPDATE tasks SET status = 'paused' WHERE batch_id = ? AND status IN ('pending', 'retrying')",
        (batch_id,)
    )
    await db.commit()
    return {"success": True}


@router.post("/batches/{batch_id}/resume")
async def resume_batch(batch_id: int):
    """恢复批次：paused 子任务恢复为 pending"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    await set_batch_status(batch_id, 'pending')
    db = await get_db()
    await db.execute(
        "UPDATE tasks SET status = 'pending' WHERE batch_id = ? AND status = 'paused'",
        (batch_id,)
    )
    await db.commit()
    await update_batch_status(batch_id)
    return {"success": True}


@router.post("/batches/{batch_id}/cancel")
async def cancel_batch(batch_id: int):
    """取消批次：所有未完成子任务标记为 cancelled"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    await set_batch_status(batch_id, 'cancelled')
    db = await get_db()
    await db.execute(
        """UPDATE tasks SET status = 'cancelled', error_message = 'Cancelled by user'
           WHERE batch_id = ? AND status IN ('pending', 'running', 'paused', 'retrying')""",
        (batch_id,)
    )
    await db.commit()
    # 释放 worker 上的任务
    async with db.execute("SELECT worker_id FROM tasks WHERE batch_id = ? AND status = 'cancelled' AND worker_id IS NOT NULL", (batch_id,)) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        await set_worker_task(row['worker_id'], None)
    return {"success": True}


@router.post("/batches/{batch_id}/retry")
async def retry_batch(batch_id: int):
    """重试批次中所有失败的子任务"""
    batch = await get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    db = await get_db()
    await db.execute(
        """UPDATE tasks SET status = 'pending', retry_count = 0, error_message = NULL, worker_id = NULL 
           WHERE batch_id = ? AND status = 'failed'""",
        (batch_id,)
    )
    await db.commit()
    await update_batch_status(batch_id)
    
    return {"success": True}


@router.get("/list")
async def list_tasks(offset: int = 0, limit: int = 100, status: Optional[str] = None, batch_id: Optional[int] = None):
    """获取子任务列表"""
    tasks = await get_all_tasks(offset, limit, status, batch_id)
    counts = await get_task_counts()
    return {"tasks": tasks, "counts": counts}


@router.get("/counts")
async def task_counts():
    """获取子任务统计"""
    return await get_task_counts()


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: int):
    """取消子任务"""
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task['status'] in ('success', 'failed'):
        raise HTTPException(status_code=400, detail="Cannot cancel completed task")
    
    await update_task_status(task_id, 'cancelled', error_message="Cancelled by user")
    if task['worker_id']:
        await set_worker_task(task['worker_id'], None)
    
    if task.get('batch_id'):
        await update_batch_status(task['batch_id'])
    
    return {"success": True}


@router.post("/retry-failed")
async def retry_failed():
    """批量重试所有失败的子任务"""
    from master.database import get_db
    db = await get_db()
    await db.execute(
        "UPDATE tasks SET status = 'pending', retry_count = 0, error_message = NULL, worker_id = NULL WHERE status = 'failed'"
    )
    await db.commit()
    return {"success": True}


@router.post("/clear-completed")
async def clear_completed():
    """清空已成功的批次和子任务记录"""
    from master.database import get_db
    db = await get_db()
    # 删除已成功的子任务
    await db.execute("DELETE FROM tasks WHERE status = 'success'")
    await db.execute("DELETE FROM tasks WHERE status = 'failed'")
    # 删除没有子任务的批次
    await db.execute(
        """DELETE FROM batches WHERE id NOT IN (SELECT DISTINCT batch_id FROM tasks WHERE batch_id IS NOT NULL)"""
    )
    await db.commit()
    return {"success": True}
