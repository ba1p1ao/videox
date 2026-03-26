#!/bin/bash
# ========================================
# VideoX 增量部署脚本 (Jenkins CI/CD)
# 仅更新代码和服务，不重装环境
# ========================================

set -e

PROJECT_DIR="/opt/videox"
LOG_FILE="/var/log/videox-deploy.log"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "$1" | tee -a "$LOG_FILE"; }
log_info() { log "${BLUE}[INFO]${NC} $1"; }
log_success() { log "${GREEN}[OK]${NC} $1"; }
log_warn() { log "${YELLOW}[WARN]${NC} $1"; }
log_error() { log "${RED}[ERROR]${NC} $1"; }

# 初始化日志
echo "===== $(date) =====" >> "$LOG_FILE"

cd "$PROJECT_DIR"

# ==================== 更新 Python 依赖 ====================
log_info "检查 Python 依赖更新..."

source "$PROJECT_DIR/venv/bin/activate"

# 比较依赖文件是否有变化
if [ -f "$PROJECT_DIR/backend/requirements.txt" ]; then
    pip install -q -r "$PROJECT_DIR/backend/requirements.txt" 2>/dev/null || {
        log_warn "依赖安装遇到问题，重试..."
        pip install -r "$PROJECT_DIR/backend/requirements.txt"
    }
    log_success "Python 依赖已更新"
fi

# ==================== 构建前端 ====================
log_info "检查前端构建..."

FRONTEND_SRC=""
if [ -d "$PROJECT_DIR/frontend_src" ] && [ -f "$PROJECT_DIR/frontend_src/package.json" ]; then
    FRONTEND_SRC="$PROJECT_DIR/frontend_src"
elif [ -d "$PROJECT_DIR/frontend" ] && [ -f "$PROJECT_DIR/frontend/package.json" ]; then
    FRONTEND_SRC="$PROJECT_DIR/frontend"
fi

if [ -n "$FRONTEND_SRC" ]; then
    cd "$FRONTEND_SRC"
    
    # 检查 package.json 是否有变化
    if [ "package.json" -nt "$PROJECT_DIR/frontend/dist/index.html" ] 2>/dev/null || \
       [ ! -d "node_modules" ]; then
        log_info "安装前端依赖..."
        npm install --silent
    fi
    
    log_info "构建前端..."
    npm run build --silent
    
    # 复制构建产物（仅当源目录不是目标目录时）
    if [ "$FRONTEND_SRC" != "$PROJECT_DIR/frontend" ]; then
        mkdir -p "$PROJECT_DIR/frontend/dist"
        cp -r dist/* "$PROJECT_DIR/frontend/dist/"
    fi
    
    cd "$PROJECT_DIR"
    log_success "前端构建完成"
else
    log_warn "未找到前端源码，跳过构建"
fi

# ==================== 设置权限 ====================
log_info "设置权限..."
chmod -R 755 "$PROJECT_DIR"

# ==================== 重启服务 ====================
log_info "重启服务..."

systemctl daemon-reload
systemctl restart videox-celery
systemctl restart videox-api

# 等待服务启动
sleep 3

# ==================== 健康检查 ====================
log_info "健康检查..."

if systemctl is-active --quiet videox-api; then
    log_success "videox-api 运行中"
else
    log_error "videox-api 启动失败"
    journalctl -u videox-api -n 20 --no-pager
    exit 1
fi

if systemctl is-active --quiet videox-celery; then
    log_success "videox-celery 运行中"
else
    log_error "videox-celery 启动失败"
    journalctl -u videox-celery -n 20 --no-pager
    exit 1
fi

# API 健康检查
if curl -sf http://localhost:8000/api/v1/health > /dev/null; then
    log_success "API 健康检查通过"
else
    log_warn "API 健康检查失败，请查看日志"
fi

log_success "部署完成！"
