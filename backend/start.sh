#!/bin/bash
# Video Downloader 一键启动脚本
# 同时启动 FastAPI 服务和 Celery Worker

echo "================================"
echo "  Video Downloader API"
echo "================================"
echo ""

# 初始化 conda
eval "$(conda shell.bash hook)"

# 激活 py310 环境
if ! conda activate py310 2>/dev/null; then
    echo "❌ 无法激活 py310 环境"
    echo "   请确保已创建: conda create -n py310 python=3.10"
    exit 1
fi

echo "✅ Python 环境: $(which python3)"

# 检查 ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  ffmpeg 未安装，部分功能可能受限"
fi

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 检查并启动 Redis
echo ""
echo "检查 Redis..."
if ! redis-cli ping &> /dev/null; then
    echo "⚠️  Redis 未运行，尝试启动..."
    if command -v redis-server &> /dev/null; then
        redis-server --daemonize yes 2>/dev/null
        sleep 1
        if redis-cli ping &> /dev/null; then
            echo "✅ Redis 已启动"
        else
            echo "⚠️  Redis 启动失败，使用内存缓存"
        fi
    else
        echo "⚠️  Redis 未安装，使用内存缓存"
        echo "   安装: sudo apt install redis-server"
    fi
else
    echo "✅ Redis 已运行"
fi

# 创建日志目录
mkdir -p logs

# 启动 Celery Worker（后台运行）
echo ""
echo "🚀 启动 Celery Worker..."
celery -A app.core.celery_app worker \
    --loglevel=warning \
    --concurrency=10 \
    --queues=parse,download,default \
    --pool=prefork \
    --logfile=logs/celery.log \
    --detach 2>/dev/null

echo "   - 日志: logs/celery.log"

# 等待 Celery 启动
sleep 2

# 启动 FastAPI 服务（前台运行）
echo ""
echo "🚀 启动 FastAPI 服务..."
echo "   - API 文档: http://localhost:8000/docs"
echo "   - 健康检查: http://localhost:8000/api/v1/health"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

# 捕获退出信号，清理 Celery
cleanup() {
    echo ""
    echo "🛑 正在停止服务..."
    pkill -f "celery.*app.core.celery_app" 2>/dev/null
    echo "✅ 服务已停止"
    exit 0
}
trap cleanup SIGINT SIGTERM

# 启动 FastAPI
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload