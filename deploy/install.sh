#!/bin/bash
# ========================================
# VideoX 一键部署脚本 (全新 Ubuntu 云主机版)
# 自动清理环境 + 自动解决报错 + 一键部署
# ========================================

set -e

# ==================== 配置变量 ====================
PROJECT_DIR="/opt/videox"
NODE_VER="22.14.0"
LOG_FILE="/var/log/videox-install.log"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ==================== 辅助函数 ====================
log() { echo -e "$1" | tee -a "$LOG_FILE"; }
log_info() { log "${BLUE}[INFO]${NC} $1"; }
log_success() { log "${GREEN}[OK]${NC} $1"; }
log_warn() { log "${YELLOW}[WARN]${NC} $1"; }
log_error() { log "${RED}[ERROR]${NC} $1"; }

get_ip() {
    local ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "${ip:-127.0.0.1}"
}

# 带重试的命令执行
retry_cmd() {
    local max_attempts=3
    local delay=5
    local attempt=1
    local cmd="$@"
    
    while [ $attempt -le $max_attempts ]; do
        log_info "执行: $cmd (尝试 $attempt/$max_attempts)"
        if eval "$cmd" >> "$LOG_FILE" 2>&1; then
            return 0
        fi
        log_warn "命令失败，${delay}秒后重试..."
        sleep $delay
        attempt=$((attempt + 1))
    done
    log_error "命令执行失败: $cmd"
    return 1
}

# 安全的 apt 安装
apt_install() {
    local packages="$@"
    log_info "安装: $packages"
    apt-get install -y $packages >> "$LOG_FILE" 2>&1 || {
        log_warn "安装失败，更新源后重试..."
        apt-get update >> "$LOG_FILE" 2>&1
        apt-get install -y $packages >> "$LOG_FILE" 2>&1
    }
}

# ==================== 清理旧环境 ====================
cleanup_old_env() {
    log_info "===== 清理旧环境 ====="
    
    # 停止服务
    systemctl stop videox-api 2>/dev/null || true
    systemctl stop videox-celery 2>/dev/null || true
    systemctl disable videox-api 2>/dev/null || true
    systemctl disable videox-celery 2>/dev/null || true
    
    # 删除服务文件
    rm -f /etc/systemd/system/videox-api.service
    rm -f /etc/systemd/system/videox-celery.service
    systemctl daemon-reload
    
    # 删除项目目录
    rm -rf "$PROJECT_DIR"
    
    # 清理 Nginx 配置
    rm -f /etc/nginx/sites-enabled/videox
    rm -f /etc/nginx/sites-available/videox
    
    # 卸载旧版 Node.js
    apt-get remove -y nodejs 2>/dev/null || true
    rm -rf /usr/local/lib/nodejs 2>/dev/null || true
    rm -f /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx 2>/dev/null || true
    
    # 清理旧的 Python 虚拟环境
    rm -rf /opt/videox/venv 2>/dev/null || true
    
    log_success "旧环境清理完成"
}

# ==================== 配置国内镜像源 ====================
setup_mirrors() {
    log_info "===== 配置国内镜像源 ====="
    
    # 获取系统版本
    local codename=$(grep VERSION_CODENAME /etc/os-release | cut -d= -f2)
    [ -z "$codename" ] && { log_warn "无法检测系统版本"; return; }
    
    # 备份原配置
    cp /etc/apt/sources.list /etc/apt/sources.list.bak.$(date +%s) 2>/dev/null || true
    
    # 配置阿里云镜像
    cat > /etc/apt/sources.list << EOF
deb http://mirrors.aliyun.com/ubuntu/ $codename main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $codename-security main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $codename-updates main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $codename-backports main restricted universe multiverse
EOF
    
    retry_cmd apt-get update
    log_success "镜像源配置完成"
}

# ==================== 安装系统依赖 ====================
install_system_deps() {
    log_info "===== 安装系统依赖 ====="
    
    apt-get update >> "$LOG_FILE" 2>&1 || true
    
    apt_install \
        build-essential curl wget git unzip rsync \
        python3 python3-pip python3-venv \
        redis-server nginx ffmpeg \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
        libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
        libpango-1.0-0 libcairo2 libpangocairo-1.0-0 \
        libx11-xcb1 libxcb-dri3-0 libatspi2.0-0
    
    log_success "系统依赖安装完成"
}

# ==================== 安装 Node.js ====================
install_nodejs() {
    log_info "===== 安装 Node.js $NODE_VER ====="
    
    # 获取架构
    local ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  NODE_ARCH="x64" ;;
        aarch64) NODE_ARCH="arm64" ;;
        *)       NODE_ARCH="$ARCH" ;;
    esac
    
    local NODE_URL="https://mirrors.tuna.tsinghua.edu.cn/nodejs-release/v${NODE_VER}/node-v${NODE_VER}-linux-${NODE_ARCH}.tar.gz"
    
    cd /tmp
    rm -f nodejs.tar.gz
    
    # 下载 (带重试)
    local downloaded=false
    for i in 1 2 3; do
        log_info "下载 Node.js (尝试 $i/3)..."
        if curl -fsSL --connect-timeout 30 "$NODE_URL" -o nodejs.tar.gz; then
            downloaded=true
            break
        fi
        sleep 3
    done
    
    if [ "$downloaded" = false ]; then
        log_error "Node.js 下载失败"
        exit 1
    fi
    
    # 解压安装
    mkdir -p /usr/local/lib/nodejs
    tar -xzf nodejs.tar.gz -C /usr/local/lib/nodejs
    rm -f nodejs.tar.gz
    
    # 创建软链接
    ln -sf /usr/local/lib/nodejs/node-v${NODE_VER}-linux-${NODE_ARCH}/bin/node /usr/local/bin/node
    ln -sf /usr/local/lib/nodejs/node-v${NODE_VER}-linux-${NODE_ARCH}/bin/npm /usr/local/bin/npm
    ln -sf /usr/local/lib/nodejs/node-v${NODE_VER}-linux-${NODE_ARCH}/bin/npx /usr/local/bin/npx
    
    # 配置 npm 淘宝镜像
    npm config set registry https://registry.npmmirror.com
    
    log_success "Node.js 安装完成: $(node -v)"
    cd - > /dev/null
}

# ==================== 复制项目文件 ====================
copy_project() {
    log_info "===== 复制项目文件 ====="
    
    local SRC_DIR="${1:-}"
    
    if [ -z "$SRC_DIR" ]; then
        log_error "请指定项目源目录"
        log_info "用法: sudo bash install.sh <项目源目录>"
        exit 1
    fi
    
    # 转换为绝对路径
    SRC_DIR="$(cd "$SRC_DIR" 2>/dev/null && pwd)" || {
        log_error "目录不存在: $SRC_DIR"
        exit 1
    }
    
    if [ ! -d "$SRC_DIR/backend" ]; then
        log_error "无效的项目目录: $SRC_DIR"
        exit 1
    fi
    
    log_info "源目录: $SRC_DIR"
    
    # 创建项目目录
    mkdir -p "$PROJECT_DIR"/{backend,frontend/dist,downloads,logs}
    mkdir -p "$PROJECT_DIR/backend"/{config,logs}
    
    # 复制后端
    rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='logs/*' --exclude='.env' \
        "$SRC_DIR/backend/" "$PROJECT_DIR/backend/" >> "$LOG_FILE" 2>&1
    
    # 复制前端构建产物
    if [ -d "$SRC_DIR/frontend/dist" ] && [ "$(ls -A $SRC_DIR/frontend/dist 2>/dev/null)" ]; then
        cp -r "$SRC_DIR/frontend/dist/"* "$PROJECT_DIR/frontend/dist/"
        log_success "前端文件复制完成"
    else
        # 复制前端源码用于构建
        if [ -d "$SRC_DIR/frontend" ]; then
            mkdir -p "$PROJECT_DIR/frontend_src"
            rsync -av --exclude='node_modules' --exclude='dist' \
                "$SRC_DIR/frontend/" "$PROJECT_DIR/frontend_src/" >> "$LOG_FILE" 2>&1
            log_info "前端源码复制完成，稍后构建"
        fi
    fi
    
    log_success "项目文件复制完成"
}

# ==================== 创建虚拟环境 ====================
create_venv() {
    log_info "===== 创建 Python 虚拟环境 ====="
    
    rm -rf "$PROJECT_DIR/venv"
    python3 -m venv "$PROJECT_DIR/venv"
    
    if [ ! -f "$PROJECT_DIR/venv/bin/activate" ]; then
        log_error "虚拟环境创建失败"
        exit 1
    fi
    
    log_success "虚拟环境创建完成"
}

# ==================== 安装 Python 依赖 ====================
install_python_deps() {
    log_info "===== 安装 Python 依赖 ====="
    
    source "$PROJECT_DIR/venv/bin/activate"
    
    # 配置 pip 镜像
    pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ 2>/dev/null || true
    pip config set install.trusted-host mirrors.aliyun.com 2>/dev/null || true
    
    pip install --upgrade pip >> "$LOG_FILE" 2>&1
    pip install gunicorn >> "$LOG_FILE" 2>&1
    
    # 安装项目依赖 (带重试)
    local max_attempts=3
    local attempt=1
    while [ $attempt -le $max_attempts ]; do
        log_info "安装项目依赖 (尝试 $attempt/$max_attempts)..."
        if pip install -r "$PROJECT_DIR/backend/requirements.txt" >> "$LOG_FILE" 2>&1; then
            break
        fi
        log_warn "安装失败，重试中..."
        attempt=$((attempt + 1))
        sleep 5
    done
    
    log_success "Python 依赖安装完成"
}

# ==================== 安装 Playwright ====================
install_playwright() {
    log_info "===== 安装 Playwright Chromium ====="
    
    source "$PROJECT_DIR/venv/bin/activate"
    
    # 安装系统依赖
    playwright install-deps chromium 2>/dev/null >> "$LOG_FILE" || true
    
    # 尝试国内镜像（带超时）
    local mirrors=(
        "https://mirrors.huaweicloud.com/playwright"
        "https://mirrors.cloud.tencent.com/playwright"
    )
    
    local installed=false
    local timeout=120  # 超时时间（秒）
    
    for mirror in "${mirrors[@]}"; do
        log_info "尝试镜像: $mirror (超时 ${timeout}s)"
        export PLAYWRIGHT_DOWNLOAD_HOST="$mirror"
        
        # 使用 timeout 命令限制时间
        if timeout $timeout playwright install chromium >> "$LOG_FILE" 2>&1; then
            installed=true
            break
        fi
    done
    
    if [ "$installed" = true ]; then
        log_success "Playwright Chromium 安装完成"
        return
    fi
    
    # 安装失败，提示手动操作
    log_warn "Playwright 浏览器自动安装失败（网络超时或镜像不可用）"
    log_warn "请按以下步骤手动安装："
    echo ""
    log "${YELLOW}========================================${NC}"
    log "${YELLOW}  手动安装 Playwright Chromium 步骤${NC}"
    log "${YELLOW}========================================${NC}"
    log ""
    log "1. 在本地电脑（有代理的环境）下载以下文件："
    log "   https://playwright.azureedge.net/builds/chromium/1208/chrome-headless-shell-linux64.zip"
    log ""
    log "   或下载普通 Chrome："
    log "   https://playwright.azureedge.net/builds/chromium/1208/chrome-linux64.zip"
    log ""
    log "2. 上传到服务器："
    log "   scp chrome-headless-shell-linux64.zip root@\$(hostname -I | awk '{print \$1}'):/tmp/"
    log ""
    log "3. 在服务器上执行："
    log ""
    log "   # 如果下载的是 chrome-headless-shell-linux64.zip"
    log "   sudo rm -rf /root/.cache/ms-playwright/chromium_headless_shell-1208"
    log "   sudo mkdir -p /root/.cache/ms-playwright/chromium_headless_shell-1208"
    log "   sudo unzip /tmp/chrome-headless-shell-linux64.zip -d /root/.cache/ms-playwright/chromium_headless_shell-1208/"
    log ""
    log "   # 如果下载的是 chrome-linux64.zip（普通 Chrome）"
    log "   sudo rm -rf /root/.cache/ms-playwright/chromium_headless_shell-1208"
    log "   sudo mkdir -p /root/.cache/ms-playwright/chromium_headless_shell-1208"
    log "   sudo unzip /tmp/chrome-linux64.zip -d /root/.cache/ms-playwright/chromium_headless_shell-1208/"
    log "   sudo mv /root/.cache/ms-playwright/chromium_headless_shell-1208/chrome-linux64 \\"
    log "           /root/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64"
    log "   sudo ln -s /root/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome \\"
    log "              /root/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell"
    log ""
    log "4. 重启服务："
    log "   sudo systemctl restart videox-api"
    log ""
    log "${YELLOW}========================================${NC}"
}

# ==================== 构建前端 ====================
build_frontend() {
    log_info "===== 构建前端 ====="
    
    local frontend_dir=""
    if [ -d "$PROJECT_DIR/frontend_src" ] && [ -f "$PROJECT_DIR/frontend_src/package.json" ]; then
        frontend_dir="$PROJECT_DIR/frontend_src"
    elif [ -f "$PROJECT_DIR/frontend/package.json" ]; then
        frontend_dir="$PROJECT_DIR/frontend"
    else
        log_warn "未找到前端源码，跳过构建"
        return
    fi
    
    cd "$frontend_dir"
    
    # 清理
    rm -rf node_modules package-lock.json
    
    # 安装依赖
    npm install >> "$LOG_FILE" 2>&1
    
    # 构建
    npm run build >> "$LOG_FILE" 2>&1
    
    # 复制产物
    mkdir -p "$PROJECT_DIR/frontend/dist"
    cp -r dist/* "$PROJECT_DIR/frontend/dist/"
    
    cd - > /dev/null
    log_success "前端构建完成"
}

# ==================== 配置环境变量 ====================
configure_env() {
    log_info "===== 配置环境变量 ====="
    
    local ip=$(get_ip)
    
    # 不覆盖已有配置
    if [ -f "$PROJECT_DIR/backend/.env" ]; then
        log_warn ".env 已存在，跳过"
        return
    fi
    
    cat > "$PROJECT_DIR/backend/.env" << EOF
DEBUG=false
HOST=0.0.0.0
PORT=8000
DOWNLOAD_DIR=$PROJECT_DIR/downloads
HTTP_TIMEOUT=30
HTTP_CONNECT_TIMEOUT=10
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
API_KEY_ENABLED=false
CORS_ORIGINS=["http://$ip", "http://localhost"]
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true
REDIS_MAX_CONNECTIONS=50
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
EOF
    
    log_success "环境变量配置完成"
}

# ==================== 配置 Nginx ====================
configure_nginx() {
    log_info "===== 配置 Nginx ====="
    
    local ip=$(get_ip)
    
    cat > /etc/nginx/sites-available/videox << 'NGINX_EOF'
server {
    listen 80 default_server;
    listen 8080;
    server_name _;
    client_max_body_size 500M;
    client_body_timeout 300s;
    
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
    
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    # 前端静态文件
    location / {
        root __PROJECT_DIR__/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
        
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
            expires 30d;
        }
    }
    
    # API 代理 - 统一 CORS 处理
    location /api/ {
        # 预检请求直接返回
        if ($request_method = OPTIONS) {
            add_header Access-Control-Allow-Origin * always;
            add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
            add_header Access-Control-Allow-Headers "*" always;
            add_header Access-Control-Max-Age 86400 always;
            add_header Content-Length 0;
            add_header Content-Type "text/plain; charset=utf-8";
            return 204;
        }
        
        # CORS 头
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header Access-Control-Allow-Headers "*" always;
        add_header Access-Control-Expose-Headers "*" always;
        
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host:$server_port;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
    
    # 静态文件代理（抖音图文图片等）
    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host:$server_port;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_cache_valid 200 7d;
        expires 7d;
        add_header Cache-Control "public, max-age=604800";
    }
}
NGINX_EOF
    
    # 替换项目路径
    sed -i "s|__PROJECT_DIR__|$PROJECT_DIR|g" /etc/nginx/sites-available/videox
    
    ln -sf /etc/nginx/sites-available/videox /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    
    # 测试配置
    if ! nginx -t >> "$LOG_FILE" 2>&1; then
        log_error "Nginx 配置有误"
        cat /etc/nginx/sites-available/videox
        exit 1
    fi
    
    log_success "Nginx 配置完成"
}

# ==================== 配置系统服务 ====================
configure_services() {
    log_info "===== 配置系统服务 ====="
    
    # API 服务
    cat > /etc/systemd/system/videox-api.service << EOF
[Unit]
Description=VideoX API Server
After=network.target redis.service

[Service]
Type=notify
User=root
WorkingDirectory=$PROJECT_DIR/backend
Environment=PATH=$PROJECT_DIR/venv/bin:/usr/bin:/bin
ExecStart=$PROJECT_DIR/venv/bin/gunicorn app.main:app --config gunicorn.conf.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    # Celery 服务
    cat > /etc/systemd/system/videox-celery.service << EOF
[Unit]
Description=VideoX Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR/backend
Environment=PATH=$PROJECT_DIR/venv/bin:/usr/bin:/bin
ExecStart=$PROJECT_DIR/venv/bin/celery -A app.core.celery_app worker --loglevel=info --concurrency=4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    log_success "系统服务配置完成"
}

# ==================== 启动服务 ====================
start_services() {
    log_info "===== 启动服务 ====="
    
    # 启动 Redis
    systemctl enable redis-server >> "$LOG_FILE" 2>&1
    systemctl start redis-server >> "$LOG_FILE" 2>&1 || systemctl restart redis-server >> "$LOG_FILE" 2>&1
    
    # 启动应用
    systemctl enable videox-api videox-celery >> "$LOG_FILE" 2>&1
    systemctl start videox-celery >> "$LOG_FILE" 2>&1
    systemctl start videox-api >> "$LOG_FILE" 2>&1
    
    # 启动 Nginx
    systemctl enable nginx >> "$LOG_FILE" 2>&1
    systemctl restart nginx >> "$LOG_FILE" 2>&1
    
    log_success "服务启动完成"
}

# ==================== 验证部署 ====================
verify_deployment() {
    log_info "===== 验证部署 ====="
    
    sleep 3
    
    # 检查服务状态
    local api_ok=false
    local celery_ok=false
    local nginx_ok=false
    
    if systemctl is-active --quiet videox-api; then
        api_ok=true
    fi
    
    if systemctl is-active --quiet videox-celery; then
        celery_ok=true
    fi
    
    if systemctl is-active --quiet nginx; then
        nginx_ok=true
    fi
    
    # API 健康检查
    if curl -sf http://127.0.0.1:8000/api/v1/health >> "$LOG_FILE" 2>&1; then
        log_success "API 健康检查通过"
    else
        log_warn "API 健康检查失败，请查看日志"
    fi
    
    echo ""
    log "${GREEN}服务状态:${NC}"
    [ "$api_ok" = true ] && log "  videox-api:   ${GREEN}运行中${NC}" || log "  videox-api:   ${RED}未运行${NC}"
    [ "$celery_ok" = true ] && log "  videox-celery: ${GREEN}运行中${NC}" || log "  videox-celery: ${RED}未运行${NC}"
    [ "$nginx_ok" = true ] && log "  nginx:         ${GREEN}运行中${NC}" || log "  nginx:         ${RED}未运行${NC}"
}

# ==================== 输出摘要 ====================
print_summary() {
    local ip=$(get_ip)
    
    echo ""
    log "${GREEN}========================================"
    log "   部署完成！"
    log "========================================${NC}"
    echo ""
    log "${GREEN}访问地址:${NC}"
    log "  前端:     http://$ip"
    log "  API 文档: http://$ip/api/v1/docs"
    echo ""
    log "${GREEN}日志文件:${NC}"
    log "  安装日志: $LOG_FILE"
    log "  应用日志: $PROJECT_DIR/backend/logs/"
    echo ""
    log "${GREEN}常用命令:${NC}"
    log "  查看状态: systemctl status videox-api"
    log "  重启服务: systemctl restart videox-api"
    log "  查看日志: tail -f $PROJECT_DIR/backend/logs/app_*.log"
    echo ""
}

# ==================== 主程序 ====================
main() {
    # 初始化日志
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "===== VideoX 部署日志 $(date) =====" > "$LOG_FILE"
    
    echo ""
    log "${BLUE}========================================${NC}"
    log "${BLUE}   VideoX 一键部署脚本${NC}"
    log "${BLUE}========================================${NC}"
    echo ""
    
    # 检查 root
    if [ "$EUID" -ne 0 ]; then
        log_error "请使用 root 权限运行"
        log_info "用法: sudo bash install.sh <项目源目录>"
        exit 1
    fi
    
    # 检查操作系统
    if [ ! -f /etc/os-release ]; then
        log_error "无法检测操作系统"
        exit 1
    fi
    . /etc/os-release
    log_info "操作系统: $PRETTY_NAME"
    
    # 执行部署步骤
    cleanup_old_env
    setup_mirrors
    install_system_deps
    install_nodejs
    copy_project "$1"
    create_venv
    install_python_deps
    install_playwright
    build_frontend
    configure_env
    configure_nginx
    configure_services
    chmod -R 755 "$PROJECT_DIR"
    start_services
    verify_deployment
    print_summary
}

main "$@"