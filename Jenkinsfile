#!/usr/bin/env groovy
// ========================================
// VideoX Jenkins Pipeline (增量部署)
// ========================================

pipeline {
    agent any
    
    environment {
        PROJECT_DIR = '/opt/videox'
    }
    
    stages {
        stage('拉取代码') {
            steps {
                echo '📥 拉取最新代码...'
                checkout scm
                sh 'git log -1 --oneline'
            }
        }
        
        stage('同步到服务器') {
            steps {
                echo '📤 同步代码到云服务器...'
                sshagent(credentials: ['videox-server-ssh']) {
                    sh '''
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
        
        stage('增量部署') {
            steps {
                echo '🚀 执行增量部署...'
                sshagent(credentials: ['videox-server-ssh']) {
                    sh '''
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_USER}@${DEPLOY_HOST} "
                            cd ${PROJECT_DIR}
                            sudo bash deploy/deploy.sh
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
                            echo '=== 服务状态 ==='
                            systemctl status videox-api --no-pager | head -3
                            systemctl status videox-celery --no-pager | head -3
                            echo '=== API 检查 ==='
                            curl -sf http://localhost:8000/api/v1/health && echo ' ✓'
                            echo '=== 访问地址 ==='
                            echo \"http://\$(hostname -I | awk '{print \$1}')\"
                        "
                    '''
                }
            }
        }
    }
    
    post {
        success {
            echo '✅ 部署成功！'
        }
        failure {
            echo '❌ 部署失败！请查看日志'
        }
    }
}
