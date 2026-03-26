#!/usr/bin/env groovy
// ========================================
// VideoX Jenkins Pipeline (本地部署版)
// ========================================

pipeline {
    agent any
    
    environment {
        // 项目配置
        PROJECT_NAME = 'videox'
        DEPLOY_DIR = '/opt/videox'
        VENV_DIR = '/opt/videox/venv'
        
        // 从 Jenkins Credentials 获取
        SERVER_HOST = credentials('server-host')
        SERVER_USER = credentials('server-user')
    }
    
    stages {
        stage('Checkout') {
            steps {
                echo '📥 拉取代码...'
                checkout scm
                sh 'git log -1 --pretty=format:"%h - %s (%ar)"'
            }
        }
        
        stage('Build Frontend') {
            steps {
                echo '🔨 构建前端...'
                sh '''
                    cd frontend
                    if [ ! -d "node_modules" ]; then
                        npm install
                    fi
                    npm run build
                '''
            }
        }
        
        stage('Deploy to Server') {
            steps {
                echo '🚀 部署到云主机...'
                sshagent(credentials: ['server-ssh-key']) {
                    // 同步代码到服务器
                    sh """
                        rsync -avz --delete \
                            --exclude='.git' \
                            --exclude='node_modules' \
                            --exclude='__pycache__' \
                            --exclude='*.pyc' \
                            --exclude='.env' \
                            --exclude='venv' \
                            --exclude='downloads' \
                            --exclude='logs/*.log' \
                            ./ ${SERVER_USER}@${SERVER_HOST}:${DEPLOY_DIR}/
                    """
                }
            }
        }
        
        stage('Install Dependencies') {
            steps {
                echo '📦 安装依赖...'
                sshagent(credentials: ['server-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_HOST} "
                            cd ${DEPLOY_DIR}
                            
                            # 创建虚拟环境（如果不存在）
                            if [ ! -d 'venv' ]; then
                                python3 -m venv venv
                            fi
                            
                            # 激活虚拟环境并安装依赖
                            source venv/bin/activate
                            pip install --upgrade pip
                            pip install gunicorn
                            pip install -r backend/requirements.txt
                            
                            # 安装 Playwright 浏览器（首次需要）
                            playwright install chromium 2>/dev/null || true
                        "
                    """
                }
            }
        }
        
        stage('Restart Services') {
            steps {
                echo '🔄 重启服务...'
                sshagent(credentials: ['server-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_HOST} "
                            # 重启 systemd 服务
                            sudo systemctl daemon-reload
                            sudo systemctl restart videox-celery
                            sudo systemctl restart videox-api
                            sudo systemctl restart nginx || true
                            
                            # 等待服务启动
                            sleep 5
                            
                            # 健康检查
                            curl -f http://localhost:8000/api/v1/health || exit 1
                            
                            echo '服务状态：'
                            sudo systemctl status videox-api --no-pager | head -5
                        "
                    """
                }
            }
        }
    }
    
    post {
        success {
            echo '✅ 部署成功！'
        }
        failure {
            echo '❌ 部署失败！'
        }
        always {
            cleanWs()
        }
    }
}
