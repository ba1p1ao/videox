"""
Celery 异步任务
处理视频解析和下载
"""
import asyncio
from typing import Optional
from loguru import logger

from .celery_app import celery_app
from ..services.downloader import downloader
from ..core.cache import cache
from ..core.config import settings


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="app.core.tasks.parse_video",
)
def parse_video_task(self, url: str, cookies: Optional[str] = None, use_cache: bool = True):
    """
    异步解析视频任务
    
    Args:
        url: 视频 URL
        cookies: Cookie 字符串
        use_cache: 是否使用缓存
    
    Returns:
        解析结果字典
    """
    try:
        # 检查缓存
        if use_cache:
            cached = run_async(cache.get_parse_result(url))
            if cached:
                logger.info(f"任务 {self.request.id}: 缓存命中")
                return {
                    "success": True,
                    "video_info": cached,
                    "from_cache": True,
                }
        
        # 执行解析
        logger.info(f"任务 {self.request.id}: 开始解析 {url}")
        video_info = run_async(downloader.parse_video_info(url, cookies=cookies))
        
        # 缓存结果
        if use_cache and video_info:
            video_dict = video_info.model_dump()
            run_async(cache.set_parse_result(url, video_dict))
        
        return {
            "success": True,
            "video_info": video_info.model_dump() if video_info else None,
            "from_cache": False,
        }
        
    except Exception as e:
        logger.error(f"任务 {self.request.id}: 解析失败 - {e}")
        
        # 重试
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return {
            "success": False,
            "error": str(e),
            "video_info": None,
        }


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="app.core.tasks.download_video",
)
def download_video_task(
    self,
    url: str,
    format_id: Optional[str] = None,
    quality: str = "best",
    audio_only: bool = False,
    cookies: Optional[str] = None,
):
    """
    异步下载视频任务
    
    Args:
        url: 视频 URL
        format_id: 格式 ID
        quality: 质量选择
        audio_only: 仅下载音频
        cookies: Cookie 字符串
    
    Returns:
        下载结果字典
    """
    try:
        logger.info(f"任务 {self.request.id}: 开始下载 {url}")
        
        file_path = run_async(
            downloader.download_async(
                url=url,
                format_id=format_id,
                quality=quality,
                audio_only=audio_only,
                cookies=cookies,
            )
        )
        
        import os
        if file_path and os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            file_name = os.path.basename(file_path)
            
            return {
                "success": True,
                "file_path": file_path,
                "file_name": file_name,
                "file_size": file_size,
            }
        
        return {
            "success": False,
            "error": "下载失败，文件不存在",
        }
        
    except Exception as e:
        logger.error(f"任务 {self.request.id}: 下载失败 - {e}")
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return {
            "success": False,
            "error": str(e),
        }


@celery_app.task(name="app.core.tasks.health_check")
def health_check_task():
    """健康检查任务"""
    return {"status": "ok", "message": "Celery worker is running"}
