#!/usr/bin/env python3
"""
打包脚本：将分布式解压系统及其依赖完整打包，用于离线部署
目标机器无需 Python 环境，解压即用
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

# 配置
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
TEMP_DIR = DIST_DIR / "temp"
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.13.2/python-3.13.2-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"


def run(cmd, cwd=None, check=True):
    """运行命令并打印输出"""
    print(f"[RUN] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def download(url, dest):
    """下载文件到指定路径，支持重试"""
    dest = Path(dest)
    if dest.exists():
        print(f"[SKIP] Already downloaded: {dest.name}")
        return
    print(f"[DOWNLOAD] {url} -> {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 尝试使用 curl（Windows 10+ 内置，更稳定）
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["curl", "-L", "-o", str(dest), url],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                print(f"[DONE] {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
                return
        except Exception:
            pass

        # 回退到 urllib
        try:
            if dest.exists():
                dest.unlink()
            urllib.request.urlretrieve(url, dest)
            if dest.exists() and dest.stat().st_size > 0:
                print(f"[DONE] {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
                return
        except Exception as e:
            print(f"[RETRY {attempt+1}/3] {e}")
            if dest.exists():
                dest.unlink()

    raise RuntimeError(f"Failed to download {url}")


def extract_zip(zip_path, dest_dir):
    """解压 zip 文件"""
    dest_dir = Path(dest_dir)
    if dest_dir.exists() and any(dest_dir.iterdir()):
        print(f"[SKIP] Already extracted: {dest_dir}")
        return
    print(f"[EXTRACT] {zip_path} -> {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(dest_dir)


def configure_embedded_python(python_dir):
    """配置 embeddable Python：启用 site-packages"""
    pth_file = python_dir / "python313._pth"
    if not pth_file.exists():
        raise FileNotFoundError(f"Expected {pth_file}")

    content = pth_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines = []
    modified = False
    for line in lines:
        if line.startswith("#import site"):
            new_lines.append("import site")
            modified = True
        else:
            new_lines.append(line)
    if "./Lib/site-packages" not in content:
        new_lines.append("./Lib/site-packages")
        modified = True

    if modified:
        pth_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"[CONFIG] Updated {pth_file.name}")
    else:
        print(f"[CONFIG] {pth_file.name} already configured")


def install_pip(python_exe, get_pip_script):
    """在 embeddable Python 中安装 pip"""
    if (python_exe.parent / "Scripts" / "pip.exe").exists():
        print("[SKIP] pip already installed")
        return
    print("[INSTALL] pip into embedded Python...")
    run([str(python_exe), str(get_pip_script), "--no-warn-script-location"])


def download_wheels(python_exe, requirements_file, wheels_dir):
    """下载所有依赖 whl"""
    wheels_dir = Path(wheels_dir)
    wheels_dir.mkdir(parents=True, exist_ok=True)
    print("[DOWNLOAD] Dependency wheels...")
    run([
        str(python_exe), "-m", "pip", "download",
        "-r", str(requirements_file),
        "-d", str(wheels_dir),
        "--only-binary=:all:",
    ])


def install_dependencies(python_exe, requirements_file, wheels_dir):
    """从本地 wheels 离线安装依赖"""
    print("[INSTALL] Dependencies from wheels...")
    run([
        str(python_exe), "-m", "pip", "install",
        "--no-index",
        "--find-links", str(wheels_dir),
        "-r", str(requirements_file),
    ])


def copy_tree(src, dst, ignore=None):
    """复制目录树"""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def generate_master_start_bat(dist_dir):
    """生成 Master 启动脚本"""
    content = '''@echo off
chcp 65001 >nul
cd /d "%~dp0"

set /p PORT="请输入绑定端口 (默认 8000): "
if "%%PORT%%"=="" set PORT=8000

set MASTER_PORT=%%PORT%%
set MASTER_HOST=0.0.0.0

echo.
echo ========================================
echo  正在启动 Master 服务
echo  绑定端口: %%PORT%%
echo  管理后台: http://localhost:%%PORT%%/dashboard
echo  默认账号: agrsadmin / agrsadmin123
echo ========================================
echo.

python\\python.exe code\\master\\main.py

pause
'''
    (dist_dir / "start.bat").write_text(content, encoding="utf-8")


def generate_worker_start_bat(dist_dir):
    """生成 Worker 启动脚本"""
    content = '''@echo off
chcp 65001 >nul
cd /d "%~dp0"

set /p MASTER_URL="请输入 Master 地址 (默认 http://localhost:8000): "
if "%%MASTER_URL%%"=="" set MASTER_URL=http://localhost:8000

set /p CONCURRENT="请输入并行任务数 (默认 1): "
if "%%CONCURRENT%%"=="" set CONCURRENT=1

set /p NAME="请输入 Worker 名称 (默认本机名): "
if "%%NAME%%"=="" set NAME=

echo.
echo ========================================
echo  正在启动 Worker 节点
echo  Master 地址: %%MASTER_URL%%
echo  并行任务数: %%CONCURRENT%%
if not "%%NAME%%"=="" echo  Worker 名称: %%NAME%%
echo ========================================
echo.

if "%%NAME%%"=="" (
    python\\python.exe code\\worker\\worker.py --master %%MASTER_URL%% --concurrent %%CONCURRENT%%
) else (
    python\\python.exe code\\worker\\worker.py --master %%MASTER_URL%% --concurrent %%CONCURRENT%% --name %%NAME%%
)

pause
'''
    (dist_dir / "start.bat").write_text(content, encoding="utf-8")


def generate_readme(dist_dir, node_type):
    """生成 README"""
    if node_type == "master":
        content = '''# 管理节点 (Master) 部署包

## 环境要求
- Windows 10/11 x64
- 无需安装 Python（已内置）

## 部署步骤
1. 将本文件夹复制到管理节点任意目录
2. 双击 `start.bat`
3. 按提示输入绑定端口（默认 8000）
4. 浏览器访问 `http://localhost:8000/dashboard`
5. 默认登录账号：`agrsadmin` / `agrsadmin123`

## 目录说明
- `python/` — Python 3.13.2 运行时及所有依赖
- `code/` — 管理端源码
- `common/` — 共享配置模块
'''
    else:
        content = '''# 计算节点 (Worker) 部署包

## 环境要求
- Windows 10/11 x64
- 无需安装 Python（已内置）

## 部署步骤
1. 将本文件夹复制到计算节点任意目录
2. 双击 `start.bat`
3. 按提示输入：
   - Master 地址（如 `http://192.168.1.100:8000`）
   - 并行任务数（默认 1，建议根据 CPU 核心数设置）
   - Worker 名称（可选，默认使用本机名）
4. Worker 将自动注册到 Master 并开始接收任务

## 目录说明
- `python/` — Python 3.13.2 运行时及所有依赖
- `code/` — 计算端源码
- `common/` — 共享配置模块
'''
    (dist_dir / "README.md").write_text(content, encoding="utf-8")


def zip_directory(src_dir, zip_path):
    """将目录压缩为 zip"""
    src_dir = Path(src_dir)
    zip_path = Path(zip_path)
    print(f"[ZIP] {src_dir} -> {zip_path}")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in src_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(src_dir.parent)
                zf.write(file, arcname)
    size = zip_path.stat().st_size / 1024 / 1024
    print(f"[DONE] {zip_path.name} ({size:.1f} MB)")


def package_node(node_type, python_dir, source_dirs):
    """打包单个节点"""
    dist_dir = DIST_DIR / node_type
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    # 复制 Python 运行时
    print(f"\n[PACK] {node_type}: copying Python runtime...")
    copy_tree(python_dir, dist_dir / "python")

    # 复制源码
    for src_name, src_path in source_dirs.items():
        dst_path = dist_dir / src_name
        print(f"[PACK] {node_type}: copying {src_name}...")
        if src_path.is_dir():
            copy_tree(src_path, dst_path, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)

    # 生成启动脚本和 README
    if node_type == "master":
        generate_master_start_bat(dist_dir)
    else:
        generate_worker_start_bat(dist_dir)
    generate_readme(dist_dir, node_type)

    return dist_dir


def main():
    print("=" * 60)
    print("  分布式解压系统 — 离线打包脚本")
    print("=" * 60)

    # 1. 重建 dist/，但保留已下载的文件
    if DIST_DIR.exists():
        print("\n[CLEAN] Removing old dist packages (keeping downloaded files)...")
        # 保留已下载的临时文件
        for item in DIST_DIR.iterdir():
            if item.name != "temp":
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # 2. 下载 embeddable Python（如有现成文件则跳过）
    embed_zip = TEMP_DIR / "python-embed.zip"
    if not embed_zip.exists() or embed_zip.stat().st_size < 10000000:
        download(PYTHON_EMBED_URL, embed_zip)
    else:
        print(f"[SKIP] Found existing {embed_zip.name} ({embed_zip.stat().st_size / 1024 / 1024:.1f} MB)")

    # 3. 解压
    python_dir = TEMP_DIR / "python"
    extract_zip(embed_zip, python_dir)

    # 4. 配置 embeddable Python
    configure_embedded_python(python_dir)

    # 5. 安装 pip
    get_pip_script = TEMP_DIR / "get-pip.py"
    download(GET_PIP_URL, get_pip_script)
    python_exe = python_dir / "python.exe"
    install_pip(python_exe, get_pip_script)

    # 6. 下载依赖 whl
    wheels_dir = TEMP_DIR / "wheels"
    download_wheels(python_exe, REQUIREMENTS, wheels_dir)

    # 7. 离线安装依赖到 embeddable Python
    install_dependencies(python_exe, REQUIREMENTS, wheels_dir)

    # 8. 组装 Master 包
    master_dist = package_node("master", python_dir, {
        "code/master": PROJECT_ROOT / "master",
        "code/common": PROJECT_ROOT / "common",
    })

    # 9. 组装 Worker 包
    worker_dist = package_node("worker", python_dir, {
        "code/worker": PROJECT_ROOT / "worker",
        "code/common": PROJECT_ROOT / "common",
    })

    # 10. 压缩
    print("\n" + "=" * 60)
    master_zip = DIST_DIR / "master.zip"
    worker_zip = DIST_DIR / "worker.zip"
    zip_directory(master_dist, master_zip)
    zip_directory(worker_dist, worker_zip)

    # 清理临时文件
    print("\n[CLEAN] Removing temp files...")
    shutil.rmtree(TEMP_DIR)

    print("\n" + "=" * 60)
    print("  打包完成！")
    print(f"  {master_zip} ({master_zip.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  {worker_zip} ({worker_zip.stat().st_size / 1024 / 1024:.1f} MB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
