"""
SQLite 异步数据库模块
"""

import os
import asyncio
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any
from common.config import DATABASE_PATH

_db: Optional[aiosqlite.Connection] = None
_db_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        async with _db_lock:
            if _db is None:
                os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
                _db = await aiosqlite.connect(DATABASE_PATH)
                _db.row_factory = aiosqlite.Row
    return _db


async def init_db():
    """初始化数据库表结构"""
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            input_path TEXT NOT NULL,
            output_root TEXT,
            status TEXT DEFAULT 'pending',
            total_subtasks INTEGER DEFAULT 0,
            completed_subtasks INTEGER DEFAULT 0,
            failed_subtasks INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status);

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER,
            input_path TEXT NOT NULL,
            output_path TEXT NOT NULL,
            archive_type TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            worker_id TEXT,
            retry_count INTEGER DEFAULT 0,
            error_message TEXT,
            total_bytes INTEGER DEFAULT 0,
            processed_bytes INTEGER DEFAULT 0,
            processed_files INTEGER DEFAULT 0,
            total_files INTEGER DEFAULT 0,
            speed_mbps REAL DEFAULT 0,
            FOREIGN KEY (batch_id) REFERENCES batches(id)
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_worker ON tasks(worker_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_batch ON tasks(batch_id);
        
        CREATE TABLE IF NOT EXISTS workers (
            id TEXT PRIMARY KEY,
            hostname TEXT,
            ip_address TEXT,
            status TEXT DEFAULT 'active',
            last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active_task_id INTEGER,
            total_tasks INTEGER DEFAULT 0,
            max_concurrent_tasks INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS stats_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_tasks INTEGER DEFAULT 0,
            pending_tasks INTEGER DEFAULT 0,
            running_tasks INTEGER DEFAULT 0,
            success_tasks INTEGER DEFAULT 0,
            failed_tasks INTEGER DEFAULT 0,
            active_workers INTEGER DEFAULT 0,
            throughput_mbps REAL DEFAULT 0,
            avg_speed_mbps REAL DEFAULT 0
        );
    """)
    
    # 升级：为已存在的 workers 表添加 max_concurrent_tasks 字段
    try:
        await db.execute("ALTER TABLE workers ADD COLUMN max_concurrent_tasks INTEGER DEFAULT 1")
    except Exception:
        pass  # 字段已存在
    
    # 插入内置管理员账号
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
    hashed = pwd_context.hash("agrsadmin123")
    await db.execute(
        "INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)",
        ("agrsadmin", hashed)
    )
    await db.commit()


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


# ---------- User CRUD ----------

async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM users WHERE username = ?", (username,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_users() -> List[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT id, username, created_at FROM users ORDER BY id") as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def create_user(username: str, password_hash: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, password_hash)
    )
    await db.commit()
    return cursor.lastrowid


async def delete_user(user_id: int):
    db = await get_db()
    await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await db.commit()


# ---------- Batch CRUD ----------

async def create_batch(input_path: str, output_root: Optional[str]) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO batches (input_path, output_root) VALUES (?, ?)",
        (input_path, output_root)
    )
    await db.commit()
    return cursor.lastrowid


async def get_batch(batch_id: int) -> Optional[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_batch_status(batch_id: int):
    """根据子任务状态自动更新 batch 状态"""
    db = await get_db()
    
    # 先检查 batch 本身是否被用户暂停或取消
    async with db.execute("SELECT status FROM batches WHERE id = ?", (batch_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            return
        batch_status = row['status']
    
    # 如果 batch 是 paused 或 cancelled，不自动更新
    if batch_status in ('paused', 'cancelled'):
        return
    
    async with db.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE batch_id = ? GROUP BY status",
        (batch_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    
    counts = {'pending': 0, 'running': 0, 'success': 0, 'failed': 0, 'retrying': 0, 'paused': 0, 'cancelled': 0}
    total = 0
    for row in rows:
        counts[row['status']] = row['cnt']
        total += row['cnt']
    
    completed = counts.get('success', 0) + counts.get('failed', 0) + counts.get('cancelled', 0)
    
    if total == 0:
        status = 'pending'
    elif completed == total:
        status = 'success' if counts.get('failed', 0) == 0 and counts.get('cancelled', 0) == 0 else 'partial'
    elif counts.get('running', 0) > 0:
        status = 'running'
    else:
        status = 'pending'
    
    fields = ["status = ?", "total_subtasks = ?", "completed_subtasks = ?", "failed_subtasks = ?"]
    values = [status, total, counts.get('success', 0), counts.get('failed', 0)]
    
    if status == 'running' and batch_status != 'running':
        fields.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    elif status in ('success', 'partial'):
        fields.append("completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)")
    
    values.append(batch_id)
    await db.execute(f"UPDATE batches SET {', '.join(fields)} WHERE id = ?", tuple(values))
    await db.commit()


async def set_batch_status(batch_id: int, status: str):
    db = await get_db()
    fields = ["status = ?"]
    values = [status]
    if status == 'running':
        fields.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    elif status in ('success', 'partial', 'cancelled'):
        fields.append("completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)")
    values.append(batch_id)
    await db.execute(f"UPDATE batches SET {', '.join(fields)} WHERE id = ?", tuple(values))
    await db.commit()


async def get_all_batches(offset: int = 0, limit: int = 100, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    db = await get_db()
    if status_filter:
        async with db.execute(
            "SELECT * FROM batches WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status_filter, limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    else:
        async with db.execute(
            "SELECT * FROM batches ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_batch_counts() -> Dict[str, int]:
    db = await get_db()
    async with db.execute(
        "SELECT status, COUNT(*) as cnt FROM batches GROUP BY status"
    ) as cursor:
        rows = await cursor.fetchall()
        counts = {'total': 0, 'pending': 0, 'running': 0, 'success': 0, 'failed': 0, 'partial': 0, 'paused': 0, 'cancelled': 0}
        for row in rows:
            counts[row['status']] = row['cnt']
            counts['total'] += row['cnt']
        return counts


async def delete_batch(batch_id: int):
    db = await get_db()
    await db.execute("DELETE FROM tasks WHERE batch_id = ?", (batch_id,))
    await db.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
    await db.commit()


# ---------- Task CRUD ----------

async def create_task(batch_id: Optional[int], input_path: str, output_path: str, archive_type: str, total_bytes: int = 0, total_files: int = 0) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO tasks (batch_id, input_path, output_path, archive_type, total_bytes, total_files)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (batch_id, input_path, output_path, archive_type, total_bytes, total_files)
    )
    await db.commit()
    return cursor.lastrowid


async def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_tasks_by_batch(batch_id: int) -> List[Dict[str, Any]]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM tasks WHERE batch_id = ? ORDER BY created_at",
        (batch_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_task_status(task_id: int, status: str, worker_id: Optional[str] = None,
                              error_message: Optional[str] = None, processed_bytes: Optional[int] = None,
                              processed_files: Optional[int] = None, speed_mbps: Optional[float] = None):
    db = await get_db()
    fields = ["status = ?"]
    values = [status]
    
    if worker_id is not None:
        fields.append("worker_id = ?")
        values.append(worker_id)
    if error_message is not None:
        fields.append("error_message = ?")
        values.append(error_message)
    if processed_bytes is not None:
        fields.append("processed_bytes = ?")
        values.append(processed_bytes)
    if processed_files is not None:
        fields.append("processed_files = ?")
        values.append(processed_files)
    if speed_mbps is not None:
        fields.append("speed_mbps = ?")
        values.append(speed_mbps)
    
    if status == 'running':
        fields.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
    elif status in ('success', 'failed'):
        fields.append("completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)")
    
    values.append(task_id)
    await db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", tuple(values))
    await db.commit()


async def get_tasks_by_status(status: str, limit: int = 100) -> List[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM tasks WHERE status = ? LIMIT ?", (status, limit)) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def dispatch_task_atomic(worker_id: str) -> Optional[Dict[str, Any]]:
    """原子方式分派一个待处理任务给 Worker，避免竞争条件"""
    db = await get_db()
    # SQLite 3.35+ 支持 UPDATE ... RETURNING
    async with db.execute(
        """UPDATE tasks SET status = 'running', worker_id = ?, started_at = CURRENT_TIMESTAMP
           WHERE id = (SELECT id FROM tasks 
                       WHERE status IN ('pending', 'retrying')
                       AND (batch_id IS NULL OR batch_id IN (SELECT id FROM batches WHERE status NOT IN ('paused', 'cancelled')))
                       ORDER BY created_at LIMIT 1)
           RETURNING *""",
        (worker_id,)
    ) as cursor:
        row = await cursor.fetchone()
        await db.commit()
        return dict(row) if row else None


async def get_all_tasks(offset: int = 0, limit: int = 100, status_filter: Optional[str] = None, batch_id: Optional[int] = None) -> List[Dict[str, Any]]:
    db = await get_db()
    
    conditions = []
    params = []
    
    if status_filter:
        conditions.append("status = ?")
        params.append(status_filter)
    if batch_id is not None:
        conditions.append("batch_id = ?")
        params.append(batch_id)
    
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    
    async with db.execute(
        f"SELECT * FROM tasks {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        tuple(params + [limit, offset])
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_task_counts() -> Dict[str, int]:
    db = await get_db()
    async with db.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
    ) as cursor:
        rows = await cursor.fetchall()
        counts = {'total': 0, 'pending': 0, 'running': 0, 'success': 0, 'failed': 0, 'retrying': 0, 'paused': 0, 'cancelled': 0}
        for row in rows:
            counts[row['status']] = row['cnt']
            counts['total'] += row['cnt']
        return counts


async def reset_running_tasks_for_worker(worker_id: str):
    """Worker 超时时，将其运行中的任务重置。增加 retry_count，超限则标记为 failed。
    使用原子 UPDATE 避免 SELECT-UPDATE 竞态。"""
    from common.config import MAX_RETRY
    db = await get_db()
    # 原子方式：超过重试次数的直接标记 failed
    await db.execute(
        """UPDATE tasks SET status = 'failed', worker_id = NULL, completed_at = CURRENT_TIMESTAMP,
           error_message = 'Worker timeout, exceeded max retry (' || CAST(retry_count + 1 AS TEXT) || ')'
           WHERE worker_id = ? AND status = 'running' AND (retry_count + 1) > ?""",
        (worker_id, MAX_RETRY)
    )
    # 未超过次数的标记为 retrying 并增加 retry_count
    await db.execute(
        """UPDATE tasks SET status = 'retrying', worker_id = NULL, retry_count = retry_count + 1
           WHERE worker_id = ? AND status = 'running'""",
        (worker_id,)
    )
    await db.commit()


async def increment_retry_count(task_id: int) -> bool:
    """增加重试次数，返回是否还可以继续重试"""
    from common.config import MAX_RETRY
    db = await get_db()
    await db.execute(
        "UPDATE tasks SET retry_count = retry_count + 1 WHERE id = ?",
        (task_id,)
    )
    await db.commit()
    async with db.execute("SELECT retry_count FROM tasks WHERE id = ?", (task_id,)) as cursor:
        row = await cursor.fetchone()
        return (row['retry_count'] <= MAX_RETRY) if row else False


async def delete_tasks_by_status(status: str):
    db = await get_db()
    await db.execute("DELETE FROM tasks WHERE status = ?", (status,))
    await db.commit()


# ---------- Worker CRUD ----------

async def register_worker(worker_id: str, hostname: str, ip_address: str, max_concurrent_tasks: int = 1):
    db = await get_db()
    # 先检查 Worker 是否已存在
    async with db.execute("SELECT id FROM workers WHERE id = ?", (worker_id,)) as cursor:
        existing = await cursor.fetchone()
    
    if existing:
        # 更新现有 Worker（保留 total_tasks 和 created_at）
        await db.execute(
            """UPDATE workers SET hostname = ?, ip_address = ?, status = 'active',
               last_heartbeat = CURRENT_TIMESTAMP, active_task_id = NULL,
               max_concurrent_tasks = ? WHERE id = ?""",
            (hostname, ip_address, max_concurrent_tasks, worker_id)
        )
    else:
        # 新建 Worker
        await db.execute(
            """INSERT INTO workers 
               (id, hostname, ip_address, status, last_heartbeat, active_task_id, total_tasks, max_concurrent_tasks, created_at)
               VALUES (?, ?, ?, 'active', CURRENT_TIMESTAMP, NULL, 0, ?, CURRENT_TIMESTAMP)""",
            (worker_id, hostname, ip_address, max_concurrent_tasks)
        )
    await db.commit()


async def update_worker_heartbeat(worker_id: str, active_task_id: Optional[int] = None):
    db = await get_db()
    if active_task_id is not None:
        await db.execute(
            "UPDATE workers SET last_heartbeat = CURRENT_TIMESTAMP, active_task_id = ? WHERE id = ?",
            (active_task_id, worker_id)
        )
    else:
        await db.execute(
            "UPDATE workers SET last_heartbeat = CURRENT_TIMESTAMP WHERE id = ?",
            (worker_id,)
        )
    await db.commit()


async def update_worker_status(worker_id: str, status: str):
    db = await get_db()
    await db.execute(
        "UPDATE workers SET status = ? WHERE id = ?",
        (status, worker_id)
    )
    await db.commit()


async def set_worker_task(worker_id: str, task_id: Optional[int]):
    db = await get_db()
    await db.execute(
        "UPDATE workers SET active_task_id = ? WHERE id = ?",
        (task_id, worker_id)
    )
    await db.commit()


async def increment_worker_tasks(worker_id: str):
    db = await get_db()
    await db.execute(
        "UPDATE workers SET total_tasks = total_tasks + 1, active_task_id = NULL WHERE id = ?",
        (worker_id,)
    )
    await db.commit()


async def get_worker(worker_id: str) -> Optional[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM workers WHERE id = ?", (worker_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_workers() -> List[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM workers ORDER BY last_heartbeat DESC") as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_active_workers() -> List[Dict[str, Any]]:
    db = await get_db()
    async with db.execute("SELECT * FROM workers WHERE status = 'active' ORDER BY last_heartbeat DESC") as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def remove_worker(worker_id: str):
    db = await get_db()
    await db.execute("DELETE FROM workers WHERE id = ?", (worker_id,))
    await db.commit()


async def get_worker_running_count(worker_id: str) -> int:
    """获取 Worker 当前正在执行的任务数"""
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) as cnt FROM tasks WHERE worker_id = ? AND status = 'running'",
        (worker_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return row['cnt'] if row else 0


async def get_worker_running_tasks(worker_id: str) -> List[Dict[str, Any]]:
    """获取 Worker 当前正在执行的任务列表"""
    db = await get_db()
    async with db.execute(
        """SELECT t.*, b.input_path as batch_input_path 
           FROM tasks t 
           LEFT JOIN batches b ON t.batch_id = b.id 
           WHERE t.worker_id = ? AND t.status = 'running' 
           ORDER BY t.started_at DESC""",
        (worker_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_worker_max_concurrent(worker_id: str, max_concurrent: int):
    """更新 Worker 的并发配置"""
    db = await get_db()
    await db.execute(
        "UPDATE workers SET max_concurrent_tasks = ? WHERE id = ?",
        (max_concurrent, worker_id)
    )
    await db.commit()


async def get_worker_all_tasks(worker_id: str, offset: int = 0, limit: int = 20, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """分页获取 Worker 的任务列表（包含所有状态）"""
    db = await get_db()
    conditions = ["t.worker_id = ?"]
    params = [worker_id]
    if status_filter:
        conditions.append("t.status = ?")
        params.append(status_filter)
    where = " AND ".join(conditions)
    async with db.execute(
        f"""SELECT t.*, b.input_path as batch_input_path 
            FROM tasks t 
            LEFT JOIN batches b ON t.batch_id = b.id 
            WHERE {where}
            ORDER BY t.created_at DESC 
            LIMIT ? OFFSET ?""",
        tuple(params + [limit, offset])
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_batch_task_counts(batch_id: int) -> Dict[str, int]:
    """统计批次各状态的任务数"""
    db = await get_db()
    async with db.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE batch_id = ? GROUP BY status",
        (batch_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    counts = {'total': 0, 'pending': 0, 'running': 0, 'success': 0, 'failed': 0, 'retrying': 0, 'paused': 0, 'cancelled': 0}
    for row in rows:
        counts[row['status']] = row['cnt']
        counts['total'] += row['cnt']
    return counts


async def get_worker_task_counts(worker_id: str) -> Dict[str, int]:
    """统计 Worker 各状态的任务数"""
    db = await get_db()
    async with db.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE worker_id = ? GROUP BY status",
        (worker_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    counts = {'total': 0, 'pending': 0, 'running': 0, 'success': 0, 'failed': 0, 'retrying': 0, 'paused': 0, 'cancelled': 0}
    for row in rows:
        counts[row['status']] = row['cnt']
        counts['total'] += row['cnt']
    return counts


# ---------- Stats ----------

async def record_stats():
    db = await get_db()
    counts = await get_task_counts()
    workers = await get_active_workers()
    
    async with db.execute(
        "SELECT AVG(speed_mbps) as avg_speed FROM tasks WHERE status = 'success' AND speed_mbps > 0"
    ) as cursor:
        row = await cursor.fetchone()
        avg_speed = row['avg_speed'] or 0
    
    async with db.execute(
        """SELECT SUM(total_bytes) / 1024.0 / 1024.0 / 60.0 as throughput 
           FROM tasks WHERE status = 'success' 
           AND completed_at > datetime('now', '-60 seconds')"""
    ) as cursor:
        row = await cursor.fetchone()
        throughput = row['throughput'] or 0
    
    await db.execute(
        """INSERT INTO stats_history 
           (total_tasks, pending_tasks, running_tasks, success_tasks, failed_tasks, 
            active_workers, throughput_mbps, avg_speed_mbps)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (counts['total'], counts.get('pending', 0) + counts.get('retrying', 0),
         counts.get('running', 0), counts.get('success', 0), counts.get('failed', 0),
         len(workers), throughput, avg_speed)
    )
    await db.commit()


async def get_recent_stats(minutes: int = 10) -> List[Dict[str, Any]]:
    db = await get_db()
    async with db.execute(
        """SELECT * FROM stats_history 
           WHERE timestamp > datetime('now', ?) 
           ORDER BY timestamp ASC""",
        (f'-{minutes} minutes',)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_latest_stats() -> Dict[str, Any]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM stats_history ORDER BY timestamp DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else {}
