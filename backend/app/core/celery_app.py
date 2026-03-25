"""
Celery 任务队列配置
用于异步处理视频解析和下载任务
"""
from celery import Celery
from loguru import logger

from .config import settings

# 创建 Celery 应用
celery_app = Celery(
    "video_downloader",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery 配置
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    
    # 任务结果配置
    result_expires=3600,  # 结果保留1小时
    
    # 任务路由
    task_routes={
        "app.core.tasks.parse_video": {"queue": "parse"},
        "app.core.tasks.download_video": {"queue": "download"},
    },
    
    # 并发配置
    worker_concurrency=10,  # 每个 worker 10 个并发
    worker_prefetch_multiplier=1,  # 每次只取一个任务
    
    # 任务重试
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


# 尝试导入任务模块
try:
    from . import tasks
    logger.debug("Celery 任务模块已加载")
except ImportError:
    logger.warning("Celery 任务模块未找到")
