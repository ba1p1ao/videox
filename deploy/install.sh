#!/bin/bash
# ========================================
# VideoX 一键部署脚本 (国内服务器版)
# 适用于 Ubuntu 20.04+ / Debian 11+
# ========================================

set -e

# ==================== 配置变量 ====================
PROJECT_DIR="/opt/videox"

# 环境状态变量
PYTHON_CMD=""
PYTHON_VER=""
PIP_OK=false
NODE_OK=false
REDIS_OK=0  # 0=未安装, 1=运行中, 2=已安装未运行
FFMPEG_OK=false
NGINX_OK=false
SYSTEMD_OK=false

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ==================== 辅助函数 ====================
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
check_cmd() { command -v "$1" &> /dev/null; }

get_server_ip() {
    local ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "${ip:-127.0.0.1}"
}

# ==================== 环境检测函数 ====================
check_os() {
    log_info "检测操作系统..."
    
    if [ ! -f /etc/os-release ]; then
        log_error "无法检测操作系统"
        exit 1
    fi
    
    . /etc/os-release
    log_info "操作系统: $PRETTY_NAME"
    
    if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
        log_error "此脚本仅支持 Ubuntu/Debian 系统"
        exit 1
    fi
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "请使用 root 权限运行: sudo bash deploy/install.sh"
        exit 1
    fi
    log_success "Root 权限检查通过"
}

check_python() {
    log_info "检查 Python..."
    
    for cmd in python3.12 python3.11 python3.10 python3; do
        if check_cmd "$cmd"; then
            local ver=$($cmd -c 'import sys; print(sys.version_info.major*100+sys.version_info.minor)' 2>/dev/null)
            if [ "$ver" -ge 310 ]; then
                PYTHON_CMD="$cmd"
                PYTHON_VER=$($cmd --version 2>&1 | awk '{print $2}')
                log_success "找到 $PYTHON_VER ($cmd)"
                return 0
            fi
        fi
    done
    
    log_warn "未找到 Python 3.10+，需要安装"
}

check_pip() {
    log_info "检查 pip..."
    if check_cmd pip3; then
        PIP_OK=true
        log_success "pip3 已安装"
    else
        log_warn "pip3 未安装"
    fi
}

check_nodejs() {
    log_info "检查 Node.js..."
    if check_cmd node; then
        local major=$(node -v 2>/dev/null | sed 's/v//' | cut -d. -f1)
        if [ "${major:-0}" -ge 16 ]; then
            NODE_OK=true
            log_success "Node.js $(node -v) 已安装"
        else
            log_warn "Node.js 版本过低，需要 16+"
        fi
    else
        log_warn "Node.js 未安装"
    fi
}

check_redis() {
    log_info "检查 Redis..."
    if check_cmd redis-server; then
        if redis-cli ping &> /dev/null; then
            REDIS_OK=1
            log_success "Redis 服务运行中"
        else
            REDIS_OK=2
            log_warn "Redis 已安装但未运行"
        fi
    else
        log_warn "Redis 未安装"
    fi
}

check_ffmpeg() {
    log_info "检查 FFmpeg..."
    if check_cmd ffmpeg; then
        FFMPEG_OK=true
        log_success "FFmpeg 已安装"
    else
        log_warn "FFmpeg 未安装"
    fi
}

check_nginx() {
    log_info "检查 Nginx..."
    if check_cmd nginx; then
        NGINX_OK=true
        log_success "Nginx 已安装"
    else
        log_warn "Nginx 未安装"
    fi
}

check_systemd() {
    log_info "检查 systemd..."
    if check_cmd systemctl; then
        SYSTEMD_OK=true
        log_success "systemd 可用"
    else
        log_warn "systemd 不可用"
    fi
}

# ==================== 安装函数 ====================
configure_apt_mirror() {
    log_info "配置 APT 国内镜像源..."
    
    local codename=$(lsb_release -cs 2>/dev/null || grep VERSION_CODENAME /etc/os-release | cut -d= -f2)
    [ -z "$codename" ] && { log_warn "无法检测系统版本，跳过镜像配置"; return; }
    
    cp /etc/apt/sources.list /etc/apt/sources.list.bak.$(date +%s) 2>/dev/null || true
    
    cat > /etc/apt/sources.list << EOF
deb http://mirrors.aliyun.com/ubuntu/ $codename main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $codename-security main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $codename-updates main restricted universe multiverse
deb http://mirrors.aliyun.com/ubuntu/ $codename-backports main restricted universe multiverse
EOF
    
    log_success "APT 镜像源配置完成"
}

install_python() {
    log_info "安装 Python 3.11..."
    
    apt update
    apt install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt update
    apt install -y python3.11 python3.11-venv python3.11-dev python3.11-distutils
    
    # 安装 pip
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11
    
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
    
    PYTHON_CMD="python3.11"
    log_success "Python 3.11 安装完成"
}

install_pip() {
    log_info "安装 pip..."
    apt install -y python3-pip
    PIP_OK=true
    log_success "pip 安装完成"
}

install_nodejs() {
    log_info "安装 Node.js 20 LTS..."
    
    # 移除旧版本
    apt remove -y nodejs 2>/dev/null || true
    
    # 使用清华镜像源安装 Node.js 20
    local NODE_VER="20.18.1"
    local ARCH=$(uname -m)
    # 转换架构名称：x86_64 -> x64, aarch64 -> arm64
    case "$ARCH" in
        x86_64)  NODE_ARCH="x64" ;;
        aarch64) NODE_ARCH="arm64" ;;
        *)       NODE_ARCH="$ARCH" ;;
    esac
    local NODE_URL="https://mirrors.tuna.tsinghua.edu.cn/nodejs-release/v${NODE_VER}/node-v${NODE_VER}-linux-${NODE_ARCH}.tar.gz"
    
    log_info "下载 Node.js from: $NODE_URL"
    
    # 下载并解压
    cd /tmp
    curl -fsSL "$NODE_URL" -o nodejs.tar.gz
    mkdir -p /usr/local/lib/nodejs
    tar -xzf nodejs.tar.gz -C /usr/local/lib/nodejs
    rm -f nodejs.tar.gz
    
    # 创建软链接
    ln -sf /usr/local/lib/nodejs/node-v${NODE_VER}-linux-${NODE_ARCH}/bin/node /usr/local/bin/node
    ln -sf /usr/local/lib/nodejs/node-v${NODE_VER}-linux-${NODE_ARCH}/bin/npm /usr/local/bin/npm
    ln -sf /usr/local/lib/nodejs/node-v${NODE_VER}-linux-${NODE_ARCH}/bin/npx /usr/local/bin/npx
    
    # 配置 npm 淘宝镜像
    npm config set registry https://registry.npmmirror.com
    
    NODE_OK=true
    log_success "Node.js 安装完成: $(node -v)"
}

install_redis() {
    log_info "安装 Redis..."
    
    apt install -y redis-server
    sed -i 's/^# supervised auto/supervised systemd/' /etc/redis/redis.conf 2>/dev/null || true
    
    systemctl enable redis-server
    systemctl start redis-server
    REDIS_OK=1
    log_success "Redis 安装完成"
}

install_ffmpeg() {
    log_info "安装 FFmpeg..."
    apt install -y ffmpeg
    FFMPEG_OK=true
    log_success "FFmpeg 安装完成"
}

install_nginx() {
    log_info "安装 Nginx..."
    apt install -y nginx
    systemctl enable nginx
    NGINX_OK=true
    log_success "Nginx 安装完成"
}

install_system_deps() {
    log_info "安装系统依赖..."
    
    apt update
    apt install -y \
        build-essential curl wget git unzip \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
        libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
        libpango-1.0-0 libcairo2 libpangocairo-1.0-0 \
        libx11-xcb1 libxcb-dri3-0 libatspi2.0-0
    
    log_success "系统依赖安装完成"
}

# ==================== 项目部署函数 ====================
setup_project_dir() {
    log_info "创建项目目录..."
    mkdir -p $PROJECT_DIR/{backend,frontend/dist,downloads,logs,venv}
    mkdir -p $PROJECT_DIR/backend/{config,logs}
    log_success "项目目录: $PROJECT_DIR"
}

copy_project_files() {
    log_info "复制项目文件..."
    
    local src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    
    # 复制后端（排除缓存和日志）
    rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='logs/*' \
        "$src_dir/backend/" $PROJECT_DIR/backend/ 2>/dev/null || \
        cp -r "$src_dir/backend/"* $PROJECT_DIR/backend/
    
    # 复制前端构建文件（如果存在）
    if [ -d "$src_dir/frontend/dist" ]; then
        cp -r "$src_dir/frontend/dist/"* $PROJECT_DIR/frontend/dist/
        log_success "前端文件复制完成"
    fi
    
    log_success "项目文件复制完成"
}

create_venv() {
    log_info "创建 Python 虚拟环境..."
    
    local py="${PYTHON_CMD:-python3}"
    $py -m venv $PROJECT_DIR/venv
    log_success "虚拟环境创建完成"
}

install_python_deps() {
    log_info "安装 Python 依赖..."
    
    source $PROJECT_DIR/venv/bin/activate
    
    # pip 镜像
    pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ 2>/dev/null || true
    pip config set install.trusted-host mirrors.aliyun.com 2>/dev/null || true
    
    pip install --upgrade pip
    pip install gunicorn
    pip install -r $PROJECT_DIR/backend/requirements.txt
    
    log_success "Python 依赖安装完成"
}

install_playwright_browser() {
    log_info "安装 Playwright Chromium..."
    
    source $PROJECT_DIR/venv/bin/activate
    
    # 先安装系统依赖
    playwright install-deps chromium 2>/dev/null || true
    
    # 尝试多个国内镜像
    local mirrors=(
        "https://mirrors.huaweicloud.com/playwright"
        "https://mirrors.cloud.tencent.com/playwright"
        "https://playwright.azureedge.net"
    )
    
    local installed=false
    for mirror in "${mirrors[@]}"; do
        log_info "尝试镜像: $mirror"
        export PLAYWRIGHT_DOWNLOAD_HOST="$mirror"
        if playwright install chromium 2>/dev/null; then
            installed=true
            break
        fi
        log_warn "镜像不可用，尝试下一个..."
    done
    
    if [ "$installed" = false ]; then
        log_warn "所有镜像都失败，跳过 Playwright 浏览器安装"
        log_info "如需 Playwright，请手动下载后放置到 ~/.cache/ms-playwright/"
    fi
    
    log_success "Playwright 安装完成"
}

build_frontend() {
    log_info "构建前端..."
    
    local src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    
    if [ -f "$src_dir/frontend/package.json" ]; then
        cd "$src_dir/frontend"
        npm install
        npm run build
        mkdir -p $PROJECT_DIR/frontend/dist
        cp -r dist/* $PROJECT_DIR/frontend/dist/
        cd - > /dev/null
        log_success "前端构建完成"
    else
        log_warn "未找到前端源码，跳过构建"
    fi
}

configure_env() {
    log_info "配置环境变量..."
    
    local ip=$(get_server_ip)
    
    cat > $PROJECT_DIR/backend/.env << EOF
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

configure_nginx() {
    log_info "配置 Nginx..."
    
    local ip=$(get_server_ip)
    
    cat > /etc/nginx/sites-available/videox << EOF
server {
    listen 80;
    server_name $ip;
    client_max_body_size 500M;
    client_body_timeout 300s;
    
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
    
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    location / {
        root $PROJECT_DIR/frontend/dist;
        index index.html;
        try_files \$uri \$uri/ /index.html;
        
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
            expires 30d;
        }
    }
    
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
    
    location /api/v1/download/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
        proxy_buffering off;
    }
}
EOF
    
    ln -sf /etc/nginx/sites-available/videox /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    log_success "Nginx 配置完成"
}

configure_systemd() {
    log_info "配置系统服务..."
    
    cat > /etc/systemd/system/videox-api.service << EOF
[Unit]
Description=VideoX API Server
After=network.target redis.service

[Service]
Type=notify
User=root
WorkingDirectory=$PROJECT_DIR/backend
Environment=PATH=$PROJECT_DIR/venv/bin
ExecStart=$PROJECT_DIR/venv/bin/gunicorn app.main:app --config gunicorn.conf.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    cat > /etc/systemd/system/videox-celery.service << EOF
[Unit]
Description=VideoX Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR/backend
Environment=PATH=$PROJECT_DIR/venv/bin
ExecStart=$PROJECT_DIR/venv/bin/celery -A app.core.celery_app worker --loglevel=info --concurrency=4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    log_success "系统服务配置完成"
}

start_services() {
    log_info "启动服务..."
    
    # Redis
    [ "$REDIS_OK" -eq 2 ] && systemctl start redis-server
    
    # 应用
    systemctl enable videox-api videox-celery
    systemctl start videox-celery
    systemctl start videox-api
    
    # Nginx
    systemctl restart nginx
    
    log_success "服务启动完成"
}

print_summary() {
    local ip=$(get_server_ip)
    
    echo ""
    echo "========================================"
    echo "   部署完成！"
    echo "========================================"
    echo ""
    echo -e "${GREEN}访问地址:${NC}"
    echo "  前端: http://$ip"
    echo "  API 文档: http://$ip/api/v1/docs"
    echo ""
    echo -e "${GREEN}常用命令:${NC}"
    echo "  查看状态: systemctl status videox-api"
    echo "  查看日志: tail -f $PROJECT_DIR/backend/logs/app_*.log"
    echo "  重启服务: systemctl restart videox-api"
    echo ""
}

# ==================== 主程序 ====================
main() {
    echo ""
    echo "========================================"
    echo "   VideoX 一键部署脚本 (国内服务器版)"
    echo "========================================"
    echo ""
    
    # 1. 基础检查
    check_root
    check_os
    
    # 2. 环境检测
    log_info "===== 环境检测 ====="
    check_python
    check_pip
    check_nodejs
    check_redis
    check_ffmpeg
    check_nginx
    check_systemd
    echo ""
    
    # 3. 配置镜像源
    log_info "===== 配置镜像源 ====="
    configure_apt_mirror
    echo ""
    
    # 4. 安装缺少的组件
    log_info "===== 安装依赖 ====="
    install_system_deps
    
    [ -z "$PYTHON_CMD" ] && install_python
    [ "$PIP_OK" = false ] && install_pip
    [ "$NODE_OK" = false ] && install_nodejs
    [ "$REDIS_OK" -eq 0 ] && install_redis
    [ "$FFMPEG_OK" = false ] && install_ffmpeg
    [ "$NGINX_OK" = false ] && install_nginx
    echo ""
    
    # 5. 部署项目
    log_info "===== 部署项目 ====="
    setup_project_dir
    copy_project_files
    create_venv
    install_python_deps
    install_playwright_browser
    build_frontend
    configure_env
    configure_nginx
    configure_systemd
    set_permissions 2>/dev/null || chmod -R 755 $PROJECT_DIR
    start_services
    
    # 6. 完成
    print_summary
}

main "$@"