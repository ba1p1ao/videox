#!/bin/bash
# ========================================
# VideoX 一键部署脚本 (国内服务器版)
# 适用于 Ubuntu 20.04+ / Debian 11+
# ========================================

set -e

# ==================== 配置变量 ====================
PROJECT_DIR="/opt/videox"
NODE_VER="22.14.0"  # Node.js 22 LTS，满足 Vite 7.x 要求

# 环境状态变量
PYTHON_CMD=""
PYTHON_VER=""
PIP_OK=false
VENV_OK=false
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
        log_error "请使用 root 权限运行: sudo bash deploy/install.sh <源目录>"
        exit 1
    fi
    log_success "Root 权限检查通过"
}

check_python() {
    log_info "检查 Python..."
    
    # 按版本优先级检测
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

check_venv() {
    log_info "检查 python3-venv..."
    local py="${PYTHON_CMD:-python3}"
    if $py -m venv --help &> /dev/null; then
        VENV_OK=true
        log_success "python3-venv 可用"
    else
        log_warn "python3-venv 未安装"
    fi
}

check_nodejs() {
    log_info "检查 Node.js..."
    if check_cmd node; then
        local version=$(node -v 2>/dev/null)
        local major=$(echo "$version" | sed 's/v//' | cut -d. -f1)
        local minor=$(echo "$version" | sed 's/v//' | cut -d. -f2)
        
        # Vite 7.x 要求: Node.js 20.19+ 或 22.12+
        local version_ok=false
        if [ "$major" -ge 23 ]; then
            version_ok=true
        elif [ "$major" -eq 22 ] && [ "$minor" -ge 12 ]; then
            version_ok=true
        elif [ "$major" -eq 20 ] && [ "$minor" -ge 19 ]; then
            version_ok=true
        fi
        
        if [ "$version_ok" = true ]; then
            NODE_OK=true
            log_success "Node.js $version 已安装，满足 Vite 7.x 要求"
        else
            log_warn "Node.js $version 版本过低，Vite 7.x 需要 20.19+ 或 22.12+"
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
    
    apt update
    log_success "APT 镜像源配置完成"
}

install_python() {
    log_info "安装 Python 3.10..."
    
    apt update
    apt install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    apt update
    apt install -y python3.10 python3.10-venv python3.10-dev
    
    # 设置默认 python3
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 2>/dev/null || true
    
    PYTHON_CMD="python3.10"
    PYTHON_VER="3.10"
    log_success "Python 3.10 安装完成"
}

install_pip() {
    log_info "安装 pip..."
    apt install -y python3-pip
    PIP_OK=true
    log_success "pip 安装完成"
}

install_venv() {
    log_info "安装 python3-venv..."
    apt install -y python3-venv python3.10-venv 2>/dev/null || apt install -y python3-venv
    VENV_OK=true
    log_success "python3-venv 安装完成"
}

install_nodejs() {
    log_info "安装 Node.js ${NODE_VER} LTS..."
    
    # 移除旧版本
    apt remove -y nodejs 2>/dev/null || true
    rm -rf /usr/local/lib/nodejs 2>/dev/null || true
    rm -f /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx 2>/dev/null || true
    
    # 转换架构名称
    local ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  NODE_ARCH="x64" ;;
        aarch64) NODE_ARCH="arm64" ;;
        *)       NODE_ARCH="$ARCH" ;;
    esac
    
    local NODE_URL="https://mirrors.tuna.tsinghua.edu.cn/nodejs-release/v${NODE_VER}/node-v${NODE_VER}-linux-${NODE_ARCH}.tar.gz"
    
    log_info "下载 Node.js: $NODE_URL"
    
    # 下载
    cd /tmp
    local retries=3
    local downloaded=false
    for i in $(seq 1 $retries); do
        if curl -fsSL --connect-timeout 30 "$NODE_URL" -o nodejs.tar.gz; then
            downloaded=true
            break
        fi
        log_warn "下载失败，重试 $i/$retries..."
        sleep 2
    done
    
    if [ "$downloaded" = false ]; then
        log_error "Node.js 下载失败，请检查网络"
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
    
    # 验证安装
    if ! check_cmd node; then
        log_error "Node.js 安装失败"
        exit 1
    fi
    
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
        build-essential curl wget git unzip rsync \
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
    mkdir -p $PROJECT_DIR/{backend,frontend/dist,downloads,logs}
    mkdir -p $PROJECT_DIR/backend/{config,logs}
    log_success "项目目录: $PROJECT_DIR"
}

copy_project_files() {
    log_info "复制项目文件..."
    
    local src_dir="${1:-}"
    
    # 验证源目录
    if [ -z "$src_dir" ] || [ ! -d "$src_dir/backend" ]; then
        log_error "找不到项目源目录"
        log_info "用法: sudo bash deploy/install.sh <项目源目录>"
        log_info "例如: sudo bash deploy/install.sh /home/user/videox"
        exit 1
    fi
    
    log_info "源目录: $src_dir"
    log_info "目标目录: $PROJECT_DIR"
    
    # 如果源目录和目标目录相同，跳过复制
    if [ "$src_dir" = "$PROJECT_DIR" ]; then
        log_info "源目录与目标目录相同，跳过文件复制"
        # 确保必要目录存在
        mkdir -p $PROJECT_DIR/frontend/dist
        mkdir -p $PROJECT_DIR/downloads
        mkdir -p $PROJECT_DIR/logs
        return
    fi
    
    # 复制后端
    rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='logs/*' --exclude='.env' \
        "$src_dir/backend/" $PROJECT_DIR/backend/
    
    # 复制 deploy 目录
    if [ -d "$src_dir/deploy" ]; then
        cp -r "$src_dir/deploy" $PROJECT_DIR/
    fi
    
    # 复制前端构建文件（如果存在）
    if [ -d "$src_dir/frontend/dist" ] && [ "$(ls -A $src_dir/frontend/dist 2>/dev/null)" ]; then
        cp -r "$src_dir/frontend/dist/"* $PROJECT_DIR/frontend/dist/
        log_success "前端文件复制完成"
    else
        log_info "前端 dist 目录不存在或为空，将稍后构建"
    fi
    
    # 复制前端源码（用于构建）
    if [ -d "$src_dir/frontend" ]; then
        mkdir -p $PROJECT_DIR/frontend_src
        rsync -av --exclude='node_modules' --exclude='dist' \
            "$src_dir/frontend/" $PROJECT_DIR/frontend_src/
    fi
    
    log_success "项目文件复制完成"
}

create_venv() {
    log_info "创建 Python 虚拟环境..."
    
    # 删除旧的虚拟环境
    rm -rf $PROJECT_DIR/venv
    
    local py="${PYTHON_CMD:-python3}"
    $py -m venv $PROJECT_DIR/venv
    
    if [ ! -f "$PROJECT_DIR/venv/bin/activate" ]; then
        log_error "虚拟环境创建失败"
        exit 1
    fi
    
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
    
    # 安装系统依赖
    playwright install-deps chromium 2>/dev/null || true
    
    # 尝试国内镜像
    local mirrors=(
        "https://mirrors.huaweicloud.com/playwright"
        "https://mirrors.cloud.tencent.com/playwright"
    )
    
    local installed=false
    for mirror in "${mirrors[@]}"; do
        log_info "尝试镜像: $mirror"
        export PLAYWRIGHT_DOWNLOAD_HOST="$mirror"
        if playwright install chromium 2>/dev/null; then
            installed=true
            break
        fi
    done
    
    # 如果国内镜像都失败，尝试官方源
    if [ "$installed" = false ]; then
        log_info "尝试官方源..."
        unset PLAYWRIGHT_DOWNLOAD_HOST
        playwright install chromium || log_warn "Playwright 浏览器安装失败，跳过"
    fi
    
    log_success "Playwright 安装完成"
}

build_frontend() {
    log_info "构建前端..."
    
    # 优先使用 frontend_src（从外部复制的情况）
    # 否则使用 PROJECT_DIR/frontend（项目目录相同的情况）
    local frontend_dir=""
    if [ -d "$PROJECT_DIR/frontend_src" ] && [ -f "$PROJECT_DIR/frontend_src/package.json" ]; then
        frontend_dir="$PROJECT_DIR/frontend_src"
    elif [ -d "$PROJECT_DIR/frontend" ] && [ -f "$PROJECT_DIR/frontend/package.json" ]; then
        frontend_dir="$PROJECT_DIR/frontend"
    fi
    
    if [ -n "$frontend_dir" ]; then
        cd "$frontend_dir"
        
        # 清理旧的 node_modules
        rm -rf node_modules package-lock.json
        
        # 安装依赖
        npm install
        
        # 构建
        npm run build
        
        # 复制构建产物
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
    
    # 如果已有 .env 则保留
    if [ -f "$PROJECT_DIR/backend/.env" ]; then
        log_warn ".env 已存在，跳过配置"
        return
    fi
    
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
    
    # 安全头
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
        # CORS 跨域配置
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type, Accept, Origin, X-Requested-With" always;
        add_header Access-Control-Max-Age 3600 always;
        
        # 预检请求直接返回
        if (\$request_method = OPTIONS) {
            add_header Access-Control-Allow-Origin * always;
            add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Authorization, Content-Type, Accept, Origin, X-Requested-With" always;
            add_header Access-Control-Max-Age 3600 always;
            add_header Content-Length 0;
            add_header Content-Type "text/plain; charset=utf-8";
            return 204;
        }
        
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
    
    location /api/v1/download/ {
        # CORS 跨域配置
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type, Accept, Origin" always;
        
        if (\$request_method = OPTIONS) {
            add_header Access-Control-Allow-Origin * always;
            add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Authorization, Content-Type, Accept, Origin" always;
            add_header Content-Length 0;
            return 204;
        }
        
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
    
    if nginx -t; then
        log_success "Nginx 配置完成"
    else
        log_error "Nginx 配置有误"
        exit 1
    fi
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
    
    # 获取源目录参数
    local SRC_DIR="${1:-}"
    
    if [ -n "$SRC_DIR" ]; then
        # 转换为绝对路径
        SRC_DIR="$(cd "$SRC_DIR" 2>/dev/null && pwd)" || {
            log_error "指定的目录不存在: $1"
            exit 1
        }
        if [ ! -d "$SRC_DIR/backend" ]; then
            log_error "指定的源目录无效: $SRC_DIR (缺少 backend 目录)"
            exit 1
        fi
        log_info "使用指定的源目录: $SRC_DIR"
    else
        log_error "请指定项目源目录"
        log_info "用法: sudo bash deploy/install.sh <项目源目录>"
        log_info "例如: sudo bash deploy/install.sh /opt/videox"
        exit 1
    fi
    
    # 1. 基础检查
    check_root
    check_os
    
    # 2. 环境检测
    log_info "===== 环境检测 ====="
    check_python
    check_pip
    check_venv
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
    [ "$VENV_OK" = false ] && install_venv
    [ "$NODE_OK" = false ] && install_nodejs
    [ "$REDIS_OK" -eq 0 ] && install_redis
    [ "$FFMPEG_OK" = false ] && install_ffmpeg
    [ "$NGINX_OK" = false ] && install_nginx
    echo ""
    
    # 5. 部署项目
    log_info "===== 部署项目 ====="
    setup_project_dir
    copy_project_files "$SRC_DIR"
    create_venv
    install_python_deps
    install_playwright_browser
    build_frontend
    configure_env
    configure_nginx
    configure_systemd
    chmod -R 755 $PROJECT_DIR
    start_services
    
    # 6. 完成
    print_summary
}

main "$@"
