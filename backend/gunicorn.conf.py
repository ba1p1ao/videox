# ========================================
# Gunicorn 配置文件（生产环境）
# ========================================

import multiprocessing
import os

# 服务器绑定
bind = "0.0.0.0:8000"

# Worker 配置
# 推荐: (2 * CPU核心数) + 1
workers = multiprocessing.cpu_count() * 2 + 1

# 使用 uvicorn worker（支持异步）
worker_class = "uvicorn.workers.UvicornWorker"

# 每个 worker 的线程数
threads = 1

# Worker 超时时间（秒）- 视频下载可能较慢
timeout = 300

# 优雅关闭超时
graceful_timeout = 30

# 保持连接超时
keepalive = 5

# 最大请求数后重启 worker（防止内存泄漏）
max_requests = 1000
max_requests_jitter = 100

# 预加载应用（减少内存，但不利于热更新）
preload_app = True

# 日志配置
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
loglevel = "info"

# 访问日志格式
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# 进程名
proc_name = "videox-api"

# 安全配置
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# 环境变量
raw_env = [
    f"PYTHONPATH={os.getcwd()}",
]
