#!/bin/bash
# Video Downloader 重启脚本

echo "================================"
echo "  Video Downloader - 重启"
echo "================================"
echo ""

echo "🛑 停止现有服务..."

# 停止 FastAPI
pkill -f "uvicorn app.main:app" 2>/dev/null && echo "   - FastAPI 已停止" || echo "   - FastAPI 未运行"

# 停止 Celery
pkill -f "celery.*app.core.celery_app" 2>/dev/null && echo "   - Celery 已停止" || echo "   - Celery 未运行"

# 等待进程完全停止
sleep 2

# 确认端口已释放
if lsof -i :8000 &>/dev/null; then
    echo "⚠️  端口 8000 仍被占用，强制清理..."
    kill -9 $(lsof -t -i :8000) 2>/dev/null
    sleep 1
fi

echo ""
echo "✅ 服务已停止"
echo ""

# 启动服务
echo "🚀 启动服务..."
exec ./start.sh
