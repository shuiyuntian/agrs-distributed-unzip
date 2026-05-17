# Distributed Unzip - 分布式解压缩系统

面向 NAS + 多台 Windows 服务器环境的轻量级分布式解压缩工具，支持 `.zip` / `.tar.gz` / `.tar` / `.gz` 格式，具备完整的 Web UI、Dashboard 监控和独立 EXE 部署能力。

---

## 架构特点

- **极简架构**：纯 Python + SQLite + HTTP，无需 Redis / RabbitMQ / Docker
- **零文件传输**：基于 NAS 共享存储，Master 与 Worker 仅传输 JSON 元数据
- **Windows 原生**：标准 Python 程序，**已打包为独立单 EXE**，双击即可运行
- **稳定可靠**：Worker 失联自动重分发、单任务失败自动重试（最多 3 次）、输出目录自动清理
- **实时监控**：Dashboard 提供吞吐速度、进度预估、Worker 负载等关键指标
- **交互式启动**：EXE 双击运行时会提示输入关键配置，无需命令行

---

## 快速开始（推荐：EXE 部署）

### 1. 部署 Master（一台服务器）

将 `master.exe` 复制到任意目录，**双击运行**：

```
请输入 Master 服务端口号 (默认 8000):
```

回车使用默认端口，或输入自定义端口。

首次运行会自动在同目录创建 `data/distributed_unzip.db` 数据库，并初始化默认管理员账号：
- 用户名：`agrsadmin`
- 密码：`agrsadmin123`

访问：
- 任务管理：`http://localhost:8000`
- Dashboard：`http://localhost:8000/dashboard`
- API 文档：`http://localhost:8000/docs`

### 2. 部署 Worker（每台计算节点）

将 `worker.exe` 复制到任意目录，**双击运行**：

```
请输入 Master 节点 URL (默认 http://localhost:8000):
请输入最大并发任务数 (默认 4):
请输入 Worker 显示名称 (默认 DESKTOP-XXXXXX):
```

回车使用默认值，或按需输入。

> **注意**：Worker 节点需确保对 NAS 的 UNC 路径有访问权限。可通过 `net use` 预先建立 SMB 会话，或在服务账户中配置。

### 3. 提交任务

在 Web UI 的"提交任务"页面，输入压缩包所在文件夹的 UNC 路径：

```
\\192.168.1.10\...\tar_gz
```

系统会自动递归扫描该目录下的所有 `.zip` / `.tar.gz` / `.tar` / `.gz` 文件，并为每个压缩包创建子任务。

---

## 开发环境部署（源码方式）

如需修改代码后重新打包，使用源码方式：

### 环境准备

- Python 3.10+
- NAS 共享目录通过 UNC 路径访问

### 安装依赖

```batch
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
```

### 启动 Master

```batch
python master/main.py
```

或使用脚本：
```batch
scripts\start_master.bat
```

### 启动 Worker

```batch
python worker/worker.py --master http://master-ip:8000 --concurrent 4
```

### 打包为 EXE

```batch
pip install pyinstaller
python scripts/build_exe.py
```

打包产物输出到 `dist_exe/` 目录：
- `master.exe` (约 41 MB)
- `worker.exe` (约 13 MB)

---

## 配置说明

通过环境变量或修改 `common/config.py`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MASTER_HOST` | `0.0.0.0` | Master 监听地址 |
| `MASTER_PORT` | `8000` | Master 监听端口 |
| `NAS_INPUT_ROOT` | `\\192.168.1.10\...\tar_gz` | NAS 输入目录（UNC 路径） |
| `NAS_OUTPUT_ROOT` | `\\192.168.1.10\...\un_tar` | NAS 输出目录（UNC 路径） |
| `WORKER_TIMEOUT` | `30` | Worker 心跳超时（秒） |
| `MAX_RETRY` | `3` | 单任务最大重试次数 |
| `USE_7Z_FALLBACK` | `false` | 是否使用 7z 作为备选解压引擎 |
| `SEVEN_ZIP_PATH` | `C:\Program Files\7-Zip\7z.exe` | 7z 路径 |

> **数据库位置**：EXE 模式下数据库自动存放在 `master.exe` 同目录的 `data/` 文件夹中，迁移时直接复制该文件夹即可保留历史数据。

---

## 任务容错机制

### Worker 意外退出

1. Master 每 10 秒检测一次 Worker 心跳
2. 超过 `WORKER_TIMEOUT`（默认 30 秒）未收到心跳 → 标记 Worker 为 `offline`
3. 该 Worker 上 `running` 状态的任务自动重置为 `retrying`
4. 其他在线 Worker 重新获取并执行这些任务
5. **输出目录自动清理**：Worker 执行解压前会删除已有的输出目录，确保不会拿到上次的半成品

### 任务失败重试

- 单任务失败（解压错误、文件损坏等）自动进入 `retrying` 状态
- `retry_count` 递增，最多重试 `MAX_RETRY`（默认 3）次
- 超过重试次数后标记为 `failed`，可在 Web UI 中手动重试

---

## 部署为 Windows 服务

Worker 可使用 NSSM 注册为 Windows 服务，实现开机自启和崩溃自动重启：

```batch
scripts\install_worker_service.bat
```

需先下载 [NSSM](https://nssm.cc/download) 并放入 PATH。

---

## 目录结构

```
distributed-unzip/
├── master/              # Master 节点源码
│   ├── main.py          # FastAPI 入口
│   ├── database.py      # SQLite 数据库
│   ├── scheduler.py     # 后台调度器（心跳检测）
│   ├── api/             # REST API
│   └── static/          # Web UI（HTML + CSS + JS）
├── worker/              # Worker 节点源码
│   └── worker.py        # Worker 主程序
├── common/              # 共享配置
├── scripts/             # 启动脚本 + 打包脚本
│   ├── build_exe.py     # PyInstaller 打包脚本
│   ├── package.py       # 离线部署包制作
│   ├── start_master.bat
│   └── start_worker.bat
├── dist_exe/            # 打包产物（master.exe + worker.exe）
├── requirements.txt
└── README.md
```

---

## 技术栈

- **后端**：FastAPI + aiosqlite + asyncio + python-jose（JWT）
- **前端**：原生 HTML5 + Vanilla JS + Chart.js
- **解压引擎**：Python `zipfile` / `tarfile`（标准库，带路径遍历防护）+ 可选 7z 回退
- **进程管理**：threading（后台解压）+ asyncio（HTTP 通信）
- **打包**：PyInstaller（单文件独立 EXE）

---

## License

MIT
