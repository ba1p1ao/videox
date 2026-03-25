"""
微博视频下载器
基于 yt-dlp 实现
"""
import os
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from loguru import logger
import yt_dlp

from ..base import YtdlpDownloader
from ..platform_handler import Platform
from ...models.video import VideoInfo, DownloadProgress


class WeiboDownloader(YtdlpDownloader):
    """微博专用下载器
    
    功能：
    - 支持微博视频下载
    - 支持 m.weibo.cn 和 weibo.com
    """
    
    platform = Platform.WEIBO
    
    URL_PATTERNS = [
        r'weibo\.com/',
        r'm\.weibo\.cn/',
        r'weibo\.tv/',
    ]
    
    def __init__(self, download_dir: Optional[Path] = None, proxy: Optional[str] = None,
                 cookies: Optional[str] = None):
        super().__init__(download_dir, proxy)
        self.cookies = cookies
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._progress_store: Dict[str, DownloadProgress] = {}
    
    async def parse_video_info(self, url: str, **kwargs) -> VideoInfo:
        """解析微博视频信息"""
        options = self._build_ydl_options(download=False)
        
        loop = asyncio.get_event_loop()
        
        def _extract():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False)
        
        try:
            raw_info = await loop.run_in_executor(self._executor, _extract)
        except Exception as e:
            logger.error(f"解析微博视频失败: {e}")
            raise Exception(f"解析微博视频失败: {e}")
        
        return self.raw_to_video_info(raw_info, url, Platform.WEIBO)
    
    async def download_video(self, url: str, quality: str = "best",
                             format_id: Optional[str] = None,
                             audio_only: bool = False, **kwargs) -> str:
        """下载微博视频"""
        task_id = f"wb_{os.urandom(4).hex()}"
        self._progress_store[task_id] = DownloadProgress(task_id)
        
        options = self._build_ydl_options(
            download=True,
            format_id=format_id,
            quality=quality,
            audio_only=audio_only,
            task_id=task_id,
        )
        
        logger.info(f"开始下载微博视频: {url}")
        
        loop = asyncio.get_event_loop()
        
        def _download():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.download([url])
        
        try:
            result = await loop.run_in_executor(self._executor, _download)
            
            if result != 0:
                raise Exception(f"下载失败，返回码: {result}")
            
            # 获取下载的文件名
            progress = self._progress_store.get(task_id)
            if progress and progress.filename:
                filepath = self.download_dir / progress.filename
                if filepath.exists():
                    logger.info(f"微博视频下载完成: {progress.filename}")
                    return str(filepath)
            
            # 如果无法获取文件名，查找最新文件
            files = sorted(
                list(self.download_dir.glob("*.mp4")),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )
            if files:
                logger.info(f"微博视频下载完成: {files[0].name}")
                return str(files[0])
            
            raise Exception("无法找到下载的文件")
        
        finally:
            self._progress_store.pop(task_id, None)
