#!/usr/bin/env groovy
// ========================================
// VideoX Jenkins Pipeline (本地部署版)
// ========================================

pipeline {
    agent any
    
    environment {
        // 项目配置
        PROJECT_DIR = '/opt/videox'
    }
    
    stages {
        stage('拉取代码') {
            steps {
                echo '📥 拉取最新代码...'
                checkout scm
                sh 'git log -1 --pretty=format:"%h - %s"'
            }
        }
        
        stage('同步到服务器') {
            steps {
                echo '📤 同步代码到云服务器...'
                sshagent(credentials: ['videox-server-ssh']) {
                    sh '''
                        # 同步代码（排除不需要的文件）
                        rsync -avz --delete \
                            --exclude='.git' \
                            --exclude='node_modules' \
                            --exclude='__pycache__' \
                            --exclude='*.pyc' \
                            --exclude='.env' \
                            --exclude='venv' \
                            --exclude='downloads/*' \
                            --exclude='logs/*.log' \
                            --exclude='*.tar.gz' \
                            --exclude='.idea' \
                            --exclude='.vscode' \
                            ./ ${DEPLOY_USER}@${DEPLOY_HOST}:${PROJECT_DIR}/
                    '''
                }
            }
        }
        
        stage('部署应用') {
            steps {
                echo '🚀 执行部署脚本...'
                sshagent(credentials: ['videox-server-ssh']) {
                    sh '''
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_USER}@${DEPLOY_HOST} "
                            cd ${PROJECT_DIR}
                            
                            # 执行部署脚本
                            sudo bash deploy/install.sh ${PROJECT_DIR}
                        "
                    '''
                }
            }
        }
        
        stage('健康检查') {
            steps {
                echo '🏥 检查服务状态...'
                sshagent(credentials: ['videox-server-ssh']) {
                    sh '''
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_USER}@${DEPLOY_HOST} "
                            # 等待服务启动
                            sleep 5
                            
                            # 检查 API
                            curl -sf http://localhost:8000/api/v1/health && echo ' API 正常'
                            
                            # 检查 Nginx
                            curl -sf http://localhost:80 && echo ' Nginx 正常'
                            
                            echo '服务状态:'
                            sudo systemctl status videox-api --no-pager | head -3
                            sudo systemctl status videox-celery --no-pager | head -3
                        "
                    '''
                }
            }
        }
    }
    
    post {
        success {
            echo '✅ 部署成功！'
            sh '''
                ssh -o StrictHostKeyChecking=no ${DEPLOY_USER}@${DEPLOY_HOST} "
                    echo \"访问地址: http://\$(hostname -I | awk '{print \$1}')\"
                "
            '''
        }
        failure {
            echo '❌ 部署失败！请检查日志'
        }
    }
}