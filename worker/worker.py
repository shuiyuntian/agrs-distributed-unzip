"""
Worker 节点主程序（支持多任务并行）
"""

import os
import sys
import time
import uuid
import socket
import logging
import threading
import zipfile
import tarfile
import subprocess
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import (
    MASTER_URL, HEARTBEAT_INTERVAL, PROGRESS_INTERVAL,
    USE_7Z_FALLBACK, SEVEN_ZIP_PATH
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("worker")


class Worker:
    def __init__(self, master_url: str = None, max_concurrent_tasks: int = 1, hostname: str = None):
        self.master_url = (master_url or MASTER_URL).rstrip('/')
        self.worker_id = str(uuid.uuid4())
        self.hostname = hostname or socket.gethostname()
        self.ip_address = socket.gethostbyname(socket.gethostname())
        self.session = requests.Session()
        self._stop_event = threading.Event()
        self._active_tasks = {}  # task_id -> thread
        self._active_tasks_lock = threading.Lock()
        self._paused = False
        self.max_concurrent_tasks = max(1, max_concurrent_tasks)
        
    def register(self):
        """向 Master 注册"""
        try:
            resp = self.session.post(
                f"{self.master_url}/api/workers/register",
                json={
                    "worker_id": self.worker_id,
                    "hostname": self.hostname,
                    "ip_address": self.ip_address,
                    "max_concurrent_tasks": self.max_concurrent_tasks
                },
                timeout=10
            )
            resp.raise_for_status()
            logger.info(f"Registered with master as {self.worker_id} ({self.hostname}), max_concurrent={self.max_concurrent_tasks}")
            return True
        except Exception as e:
            logger.error(f"Registration failed: {e}")
            return False
    
    def heartbeat(self):
        """发送心跳，返回 Master 下发的状态指令"""
        try:
            with self._active_tasks_lock:
                # 上报第一个活跃任务的 ID（兼容旧版）
                active_task_ids = list(self._active_tasks.keys())
                active_task_id = active_task_ids[0] if active_task_ids else None
            
            resp = self.session.post(
                f"{self.master_url}/api/workers/{self.worker_id}/heartbeat",
                json={"active_task_id": active_task_id},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get('status', 'active')
        except Exception as e:
            logger.warning(f"Heartbeat failed: {e}")
            return None
    
    def handle_master_status(self, status: str) -> bool:
        """处理 Master 下发的状态指令，返回 False 表示 Worker 应该退出主循环"""
        if status == 'paused':
            if not self._paused:
                logger.info("Worker paused by master, stopping task polling")
                self._paused = True
            return True
        elif status == 'active':
            if self._paused:
                logger.info("Worker resumed by master, resuming task polling")
                self._paused = False
            return True
        elif status == 'restarting':
            logger.info("Worker restarting by master command, exiting...")
            self._stop_event.set()
            return False
        elif status == 'offline':
            logger.warning("Worker marked offline by master, re-registering...")
            self.register()
            return True
        return True
    
    def poll_task(self):
        """拉取任务"""
        try:
            resp = self.session.get(
                f"{self.master_url}/api/tasks/poll",
                params={"worker_id": self.worker_id},
                timeout=10
            )
            if resp.status_code == 204 or resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            if data:
                return data
            return None
        except Exception as e:
            logger.warning(f"Poll task failed: {e}")
            return None
    
    def report_progress(self, task_id: int, processed_bytes: int, processed_files: int, speed_mbps: float):
        """上报进度"""
        try:
            resp = self.session.post(
                f"{self.master_url}/api/tasks/{task_id}/progress",
                params={
                    "worker_id": self.worker_id,
                    "processed_bytes": processed_bytes,
                    "processed_files": processed_files,
                    "speed_mbps": round(speed_mbps, 2)
                },
                timeout=10
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Progress report failed: {e}")
    
    def report_complete(self, task_id: int):
        """上报完成"""
        try:
            resp = self.session.post(
                f"{self.master_url}/api/tasks/{task_id}/complete",
                params={"worker_id": self.worker_id},
                timeout=10
            )
            resp.raise_for_status()
            logger.info(f"Task {task_id} completed")
        except Exception as e:
            logger.error(f"Complete report failed: {e}")
    
    def report_fail(self, task_id: int, error: str):
        """上报失败"""
        try:
            resp = self.session.post(
                f"{self.master_url}/api/tasks/{task_id}/fail",
                params={"worker_id": self.worker_id, "error": error},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            logger.warning(f"Task {task_id} failed: {error}, will_retry={data.get('will_retry', False)}")
        except Exception as e:
            logger.error(f"Fail report failed: {e}")
    
    def _get_dir_size(self, path: str) -> int:
        """获取目录大小"""
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
        except:
            pass
        return total
    
    def _count_files(self, path: str) -> int:
        """统计文件数"""
        count = 0
        try:
            for _, _, filenames in os.walk(path):
                count += len(filenames)
        except:
            pass
        return count
    
    def _extract_with_7z(self, input_path: str, output_path: str) -> None:
        """使用 7z 解压（备选方案）"""
        if not os.path.exists(SEVEN_ZIP_PATH):
            raise RuntimeError("7z not found at configured path")
        
        os.makedirs(output_path, exist_ok=True)
        result = subprocess.run(
            [SEVEN_ZIP_PATH, "x", "-y", f"-o{output_path}", input_path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"7z failed: {result.stderr}")
    
    def _extract_zip(self, input_path: str, output_path: str, progress_callback) -> None:
        """解压 ZIP，带进度回调（安全模式）"""
        os.makedirs(output_path, exist_ok=True)
        
        with zipfile.ZipFile(input_path, 'r') as zf:
            total = sum(info.file_size for info in zf.infolist())
            extracted = 0
            file_count = 0
            
            for info in zf.infolist():
                # 拒绝路径遍历和绝对路径
                if info.filename.startswith('/') or '..' in info.filename.split('/'):
                    logger.warning(f"Skipping unsafe zip entry: {info.filename}")
                    continue
                if not self._is_safe_extract_path(info.filename, output_path):
                    logger.warning(f"Skipping zip entry outside output path: {info.filename}")
                    continue
                zf.extract(info, output_path)
                extracted += info.file_size
                file_count += 1
                progress_callback(extracted, file_count, total)
    
    def _is_safe_extract_path(self, member_name: str, output_path: str) -> bool:
        """验证解压目标路径是否在允许的输出目录内"""
        target = os.path.normpath(os.path.join(output_path, member_name))
        output_norm = os.path.normpath(output_path)
        return target.startswith(output_norm + os.sep) or target == output_norm

    def _extract_tar(self, input_path: str, output_path: str, progress_callback, mode: str = 'r:gz') -> None:
        """解压 TAR/TAR.GZ，带进度回调（安全模式）"""
        os.makedirs(output_path, exist_ok=True)
        
        with tarfile.open(input_path, mode) as tf:
            members = tf.getmembers()
            total = sum(m.size for m in members)
            extracted = 0
            file_count = 0
            
            for member in members:
                # 拒绝绝对路径和路径遍历
                if member.name.startswith('/') or '..' in member.name.split('/'):
                    logger.warning(f"Skipping unsafe tar member: {member.name}")
                    continue
                if not self._is_safe_extract_path(member.name, output_path):
                    logger.warning(f"Skipping tar member outside output path: {member.name}")
                    continue
                tf.extract(member, output_path)
                extracted += member.size
                file_count += 1
                progress_callback(extracted, file_count, total)
    
    def _normalize_path(self, path: str) -> str:
        """规范化路径，处理 msys/cygwin 风格路径，并确保 UNC 路径正确"""
        if not path:
            return path
        # 检测 UNC 路径（\\server\share 或 //server/share）
        if path.startswith('\\\\') or path.startswith('//'):
            # UNC 路径统一用 Windows 反斜杠格式
            return path.replace('/', '\\')
        # 非 UNC 路径：将正斜杠转为反斜杠（Windows 原生格式）
        path = path.replace('/', '\\')
        # 将 \c\Users\... 转换为 C:\Users\...（Cygwin/MSYS 风格）
        if len(path) > 2 and path[0] == '\\' and path[2] == '\\' and path[1].isalpha():
            drive = path[1].upper()
            rest = path[3:]
            path = f"{drive}:\\{rest}"
        return path

    def execute_task(self, task: dict):
        """在后台线程中执行任务"""
        task_id = task['id']
        input_path = self._normalize_path(task['input_path'])
        output_path = self._normalize_path(task['output_path'])
        archive_type = task['archive_type']
        
        logger.info(f"Starting task {task_id}: {input_path} -> {output_path}")
        
        start_time = time.time()
        last_report_time = start_time
        last_processed = 0
        
        def progress_callback(processed_bytes, file_count, total_bytes):
            nonlocal last_report_time, last_processed
            now = time.time()
            if now - last_report_time >= PROGRESS_INTERVAL:
                elapsed = now - start_time
                speed_mbps = (processed_bytes / 1024 / 1024) / elapsed if elapsed > 0 else 0
                self.report_progress(task_id, processed_bytes, file_count, speed_mbps)
                last_report_time = now
                last_processed = processed_bytes
        
        try:
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Archive not found: {input_path}")
            
            # 清理已有输出目录（避免残留）
            if os.path.exists(output_path):
                import shutil
                shutil.rmtree(output_path)
            
            if USE_7Z_FALLBACK and os.path.exists(SEVEN_ZIP_PATH):
                self._extract_with_7z(input_path, output_path)
                # 7z 无实时进度，完成后一次性上报
                total_size = self._get_dir_size(output_path)
                file_count = self._count_files(output_path)
                elapsed = time.time() - start_time
                speed = (total_size / 1024 / 1024) / elapsed if elapsed > 0 else 0
                self.report_progress(task_id, total_size, file_count, speed)
            else:
                if archive_type == 'zip':
                    self._extract_zip(input_path, output_path, progress_callback)
                elif archive_type in ('tar.gz', 'tgz'):
                    self._extract_tar(input_path, output_path, progress_callback, 'r:gz')
                elif archive_type == 'tar':
                    self._extract_tar(input_path, output_path, progress_callback, 'r')
                elif archive_type == 'gz':
                    # 单个 gzip 文件
                    import gzip
                    os.makedirs(output_path, exist_ok=True)
                    out_file = os.path.join(output_path, os.path.basename(input_path)[:-3])
                    with gzip.open(input_path, 'rb') as f_in, open(out_file, 'wb') as f_out:
                        import shutil
                        shutil.copyfileobj(f_in, f_out)
                else:
                    raise ValueError(f"Unsupported archive type: {archive_type}")
            
            self.report_complete(task_id)
            
        except Exception as e:
            logger.exception(f"Task {task_id} failed")
            self.report_fail(task_id, str(e))
        finally:
            with self._active_tasks_lock:
                self._active_tasks.pop(task_id, None)
    
    def run(self):
        """Worker 主循环（支持多任务并行）"""
        if not self.register():
            logger.error("Failed to register with master, retrying in 10s...")
            time.sleep(10)
            if not self.register():
                logger.error("Registration failed again, exiting")
                return
        
        logger.info(f"Worker main loop started, max_concurrent={self.max_concurrent_tasks}")
        
        while not self._stop_event.is_set():
            # 发送心跳，获取 Master 状态指令
            master_status = self.heartbeat()
            if master_status:
                should_continue = self.handle_master_status(master_status)
                if not should_continue:
                    break
            
            # 检查当前活跃任务数
            with self._active_tasks_lock:
                active_count = len(self._active_tasks)
            
            # 尝试拉取新任务，直到达到并发上限
            while not self._paused and active_count < self.max_concurrent_tasks:
                task = self.poll_task()
                if not task:
                    break
                task_id = task['id']
                with self._active_tasks_lock:
                    self._active_tasks[task_id] = True
                # 在后台线程中执行任务
                thread = threading.Thread(target=self.execute_task, args=(task,), daemon=True)
                thread.start()
                active_count += 1
            
            # 等待下一个心跳周期
            self._stop_event.wait(HEARTBEAT_INTERVAL)
    
    def stop(self):
        """停止 Worker"""
        logger.info("Stopping worker...")
        self._stop_event.set()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Distributed Unzip Worker")
    parser.add_argument("--master", default=None, help="Master URL (e.g. http://192.168.1.10:8000)")
    parser.add_argument("--concurrent", type=int, default=None, help="Maximum concurrent tasks (default: 4)")
    parser.add_argument("--name", default=None, help="Worker display name (default: system hostname)")
    parser.add_argument("--once", action="store_true", help="Run one task and exit")
    args = parser.parse_args()
    
    # Interactive input when launched by double-click (no extra CLI args)
    master_url = args.master
    concurrent = args.concurrent
    name = args.name
    
    if len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty():
        if master_url is None:
            try:
                user_url = input(f"请输入 Master 节点 URL (默认 {MASTER_URL}): ").strip()
                if user_url:
                    master_url = user_url
            except (ValueError, EOFError):
                pass
        if master_url is None:
            master_url = MASTER_URL
        
        if concurrent is None:
            try:
                user_concurrent = input("请输入最大并发任务数 (默认 4): ").strip()
                if user_concurrent:
                    concurrent = int(user_concurrent)
            except (ValueError, EOFError):
                pass
        if concurrent is None:
            concurrent = 4
        
        if name is None:
            try:
                user_name = input(f"请输入 Worker 显示名称 (默认 {socket.gethostname()}): ").strip()
                if user_name:
                    name = user_name
            except (ValueError, EOFError):
                pass
    else:
        if master_url is None:
            master_url = MASTER_URL
        if concurrent is None:
            concurrent = 4
    
    worker = Worker(master_url=master_url, max_concurrent_tasks=concurrent, hostname=name)
    
    try:
        if args.once:
            if worker.register():
                task = worker.poll_task()
                if task:
                    worker.execute_task(task)
                else:
                    logger.info("No task available")
        else:
            worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
