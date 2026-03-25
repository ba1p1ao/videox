#!/bin/bash
# ========================================
# VideoX 一键部署脚本
# 适用于 Ubuntu 20.04+ / CentOS 8+
# ========================================

set -e

# 配置变量
PROJECT_DIR="/opt/videox"
DOMAIN="your-domain.com"  # 替换为你的域名
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "127.0.0.1")

echo "================================"
echo "  VideoX 部署脚本"
echo "================================"
echo ""

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请使用 root 权限运行此脚本"
    echo "   sudo bash deploy/deploy.sh"
    exit 1
fi

# 1. 安装系统依赖
echo "📦 安装系统依赖..."
apt update && apt install -y \
    python3 python3-pip python3-venv \
    nginx redis-server ffmpeg \
    curl wget git

# 2. 创建项目目录
echo "📁 创建项目目录..."
mkdir -p $PROJECT_DIR/{backend,frontend,downloads,logs}
mkdir -p $PROJECT_DIR/backend/{config,logs}

# 3. 复制项目文件
echo "📋 复制项目文件..."
# 假设当前目录是项目根目录
cp -r backend/* $PROJECT_DIR/backend/
cp -r frontend/dist $PROJECT_DIR/frontend/

# 4. 创建虚拟环境
echo "🐍 创建 Python 虚拟环境..."
python3 -m venv $PROJECT_DIR/venv
source $PROJECT_DIR/venv/bin/activate

# 5. 安装 Python 依赖
echo "📦 安装 Python 依赖..."
pip install --upgrade pip
pip install gunicorn
pip install -r $PROJECT_DIR/backend/requirements.txt

# 6. 安装 Playwright 浏览器
echo "🌐 安装 Playwright 浏览器..."
playwright install chromium

# 7. 配置环境变量
echo "⚙️ 配置环境变量..."
cp deploy/.env.production $PROJECT_DIR/backend/.env

# 更新 CORS 配置
sed -i "s|your-domain.com|$DOMAIN|g" $PROJECT_DIR/backend/.env
sed -i "s|your-server-ip|$SERVER_IP|g" $PROJECT_DIR/backend/.env

# 8. 配置 Nginx
echo "🌐 配置 Nginx..."
cp deploy/nginx.conf /etc/nginx/sites-available/videox
ln -sf /etc/nginx/sites-available/videox /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 更新域名配置
sed -i "s|your-domain.com|$DOMAIN|g" /etc/nginx/sites-available/videox

# 9. 配置 systemd 服务
echo "🔧 配置系统服务..."
cp deploy/videox-api.service /etc/systemd/system/
cp deploy/videox-celery.service /etc/systemd/system/

# 更新路径配置
sed -i "s|/opt/videox|$PROJECT_DIR|g" /etc/systemd/system/videox-*.service

# 10. 设置权限
echo "🔐 设置权限..."
chown -R www-data:www-data $PROJECT_DIR
chmod -R 755 $PROJECT_DIR
chmod +x $PROJECT_DIR/backend/start.sh 2>/dev/null || true

# 11. 启动服务
echo "🚀 启动服务..."
systemctl daemon-reload
systemctl enable redis-server
systemctl enable videox-api
systemctl enable videox-celery
systemctl start redis-server
systemctl start videox-celery
systemctl start videox-api

# 12. 重启 Nginx
echo "🌐 重启 Nginx..."
nginx -t && systemctl restart nginx

echo ""
echo "================================"
echo "  ✅ 部署完成！"
echo "================================"
echo ""
echo "访问地址:"
echo "  - 前端: http://$DOMAIN"
echo "  - API 文档: http://$DOMAIN/docs"
echo ""
echo "常用命令:"
echo "  - 查看状态: systemctl status videox-api"
echo "  - 查看日志: tail -f $PROJECT_DIR/backend/logs/app_*.log"
echo "  - 重启服务: systemctl restart videox-api"
echo ""
