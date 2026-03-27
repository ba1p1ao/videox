"""
Bilibili 视频下载器
基于 yt-dlp 实现 B站视频下载
支持多P视频选集
"""
import os
import re
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tempfile

from loguru import logger
import yt_dlp

from ..base import YtdlpDownloader
from ..platform_handler import Platform
from ...models.video import VideoInfo, VideoFormat, DownloadProgress


class BilibiliDownloader(YtdlpDownloader):
    """Bilibili 专用下载器
    
    功能：
    - 支持普通视频、番剧、影视下载
    - 支持多P视频选集解析和下载
    - 自动选择最佳画质
    - 支持 Cookie 登录（获取更高画质）
    - 自动合并音视频流
    """
    
    platform = Platform.BILIBILI
    
    URL_PATTERNS = [
        r'bilibili\.com/video/',
        r'bilibili\.com/bangumi/',
        r'b23\.tv/',
        r'acg\.video\.qq\.com',
    ]
    
    # 文件名中不允许的字符（yt-dlp 会替换这些）
    INVALID_FILENAME_CHARS = r'<>:"/\|?*'
    
    # 默认 Cookie 文件路径
    DEFAULT_COOKIE_FILE = "/opt/videox/backend/config/bilibili_cookies.json"
    
    def __init__(self, download_dir: Optional[Path] = None, proxy: Optional[str] = None,
                 cookies: Optional[str] = None):
        super().__init__(download_dir, proxy)
        # 如果没有传入 cookies，尝试从默认文件加载
        if not cookies and os.path.exists(self.DEFAULT_COOKIE_FILE):
            self.cookies = self._load_cookies_from_json(self.DEFAULT_COOKIE_FILE)
            logger.info(f"自动加载 B站 Cookie 文件: {self.DEFAULT_COOKIE_FILE}")
        else:
            self.cookies = cookies
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._progress_store: Dict[str, DownloadProgress] = {}
    
    def _load_cookies_from_json(self, json_path: str) -> str:
        """从 JSON 文件加载 Cookie，返回 Cookie 字符串"""
        import json
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                cookies_dict = json.load(f)
            # 转换为 Cookie 字符串格式
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])
            return cookie_str
        except Exception as e:
            logger.warning(f"加载 Cookie JSON 文件失败: {e}")
            return None
    
    def _sanitize_filename(self, filename: str, max_length: int = 80) -> str:
        """清理文件名，匹配 yt-dlp 的行为"""
        # 替换不允许的字符为下划线
        for char in self.INVALID_FILENAME_CHARS:
            filename = filename.replace(char, '_')
        # 移除控制字符
        filename = ''.join(c for c in filename if ord(c) >= 32)
        # 截断长度
        if len(filename) > max_length:
            filename = filename[:max_length]
        # 移除首尾空格和点
        filename = filename.strip(' .')
        return filename
    
    def _build_expected_filename_pattern(self, video_title: str, video_id: str, p_index: Optional[int] = None) -> str:
        """构建预期的文件名模式
        
        多P视频文件名格式：{title} p{index} {part_title}_{id}_p{index}.{ext}
        单视频文件名格式：{title}_{id}.{ext}
        """
        clean_title = self._sanitize_filename(video_title, max_length=80)
        
        if p_index is not None:
            # 多P视频
            return f"*_{video_id}_p{p_index}.*"
        else:
            # 单视频
            return f"{clean_title}_{video_id}.*"
    
    def _build_bilibili_options(self, download: bool = False, format_id: Optional[str] = None,
                                quality: str = "best", audio_only: bool = False,
                                task_id: Optional[str] = None,
                                need_audio: bool = False,
                                playlist_items: Optional[str] = None) -> Dict[str, Any]:
        """构建 B站专用 yt-dlp 配置
        
        Args:
            playlist_items: 指定下载的播放列表项，如 "1" 或 "2,3"
        """
        options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": 60,
            "retries": 3,
        }

        # 代理设置
        if self.proxy:
            options["proxy"] = self.proxy

        # B站专用 Headers
        options["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # Cookie 支持
        if self.cookies:
            cookie_content = self._convert_cookie_to_netscape(self.cookies, ".bilibili.com")
            cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            cookie_file.write(cookie_content)
            cookie_file.close()
            options["cookiefile"] = cookie_file.name

        # 输出模板
        options["outtmpl"] = {
            "default": str(self.download_dir / "%(title).80s_%(id)s.%(ext)s"),
        }

        # 播放列表项选择（用于多P视频）
        if playlist_items:
            options["playlist_items"] = playlist_items
            logger.info(f"只下载播放列表项: {playlist_items}")

        # 格式选择
        if audio_only:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        elif format_id:
            if need_audio:
                options["format"] = f"{format_id}+bestaudio/bestvideo+bestaudio/best"
            else:
                options["format"] = f"{format_id}/bestvideo+bestaudio/best"
        else:
            format_map = {
                "best": "bestvideo+bestaudio/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
                "audio": "bestaudio/best",
            }
            options["format"] = format_map.get(quality, format_map["best"])
        
        # 下载进度回调
        if download and task_id:
            options["progress_hooks"] = [self._get_progress_hook(task_id)]
        
        # 合并格式
        options["merge_output_format"] = "mp4"
        
        return options
    
    async def parse_video_info(self, url: str, **kwargs) -> VideoInfo:
        """解析 B站视频信息，支持多P视频"""
        # 处理 b23.tv 短链接
        if 'b23.tv' in url:
            url = self.resolve_short_url(url)
        
        # 提取 URL 中的分P参数
        parsed_p = self._extract_p_index(url)
        if parsed_p:
            logger.info(f"URL 指定分P: {parsed_p}")
        
        options = self._build_bilibili_options(download=False)
        
        loop = asyncio.get_event_loop()
        
        def _extract():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False)
        
        try:
            raw_info = await loop.run_in_executor(self._executor, _extract)
        except Exception as e:
            logger.error(f"解析 B站视频失败: {e}")
            raise Exception(f"解析 B站视频失败: {e}")
        
        return self.raw_to_video_info(raw_info, url, Platform.BILIBILI)
    
    def _extract_p_index(self, url: str) -> Optional[int]:
        """从 URL 提取分P索引"""
        # ?p=1 或 ?p=2
        match = re.search(r'[?&]p=(\d+)', url)
        if match:
            return int(match.group(1))
        return None
    
    async def download_video(self, url: str, quality: str = "best", 
                             format_id: Optional[str] = None,
                             audio_only: bool = False,
                             video_title: Optional[str] = None,
                             video_id: Optional[str] = None,
                             **kwargs) -> str:
        """下载 B站视频，支持多P视频选择下载"""
        # 处理 b23.tv 短链接
        if 'b23.tv' in url:
            url = self.resolve_short_url(url)
        
        # 提取 URL 中的分P参数或从 format_id 解析
        playlist_items = None
        p_index = self._extract_p_index(url)
        
        # 如果 format_id 是 p1, p2, p3 格式，提取分P索引
        if format_id and format_id.startswith('p') and format_id[1:].isdigit():
            p_index = int(format_id[1:])
            format_id = None  # 清除 format_id，使用默认格式
        
        if p_index:
            playlist_items = str(p_index)
            logger.info(f"将下载第 {p_index} 个分P")
        
        task_id = f"bili_{os.urandom(4).hex()}"
        self._progress_store[task_id] = DownloadProgress(task_id)
        
        # 检查是否需要添加音频流
        need_audio = False
        if format_id and not audio_only:
            try:
                video_info = await self.parse_video_info(url)
                if not video_id:
                    video_id = video_info.id
                
                for fmt in video_info.formats:
                    if fmt.format_id == format_id:
                        vcodec = fmt.vcodec or "none"
                        acodec = fmt.acodec or "none"
                        if vcodec != "none" and acodec == "none":
                            need_audio = True
                            logger.info(f"格式 {format_id} 是纯视频流，将自动添加音频流")
                        break
            except Exception as e:
                logger.warning(f"解析格式信息失败: {e}")
        
        options = self._build_bilibili_options(
            download=True,
            format_id=format_id,
            quality=quality,
            audio_only=audio_only,
            task_id=task_id,
            need_audio=need_audio,
            playlist_items=playlist_items,
        )
        
        logger.info(f"开始下载 B站视频: {url}")
        
        loop = asyncio.get_event_loop()
        
        def _download():
            with yt_dlp.YoutubeDL(options) as ydl:
                return ydl.download([url])
        
        try:
            result = await loop.run_in_executor(self._executor, _download)
            
            if result != 0:
                raise Exception(f"下载失败，返回码: {result}")
            
            logger.info(f"yt-dlp 下载完成，开始查找文件...")
            
            # 方法1：通过进度回调获取文件名
            progress = self._progress_store.get(task_id)
            if progress and progress.filename:
                filepath = self.download_dir / progress.filename
                if filepath.exists():
                    logger.info(f"B站视频下载完成: {progress.filename}")
                    return str(filepath)
                logger.info(f"进度回调文件不存在: {filepath}")
            
            # 方法2：通过 BV 号和分P索引匹配
            bv_match = re.search(r'(BV[a-zA-Z0-9]+)', url)
            if bv_match:
                bv_id = bv_match.group(1)
                
                # 构建搜索模式
                if p_index:
                    # 多P视频，搜索特定分P
                    search_pattern = f"*_p{p_index}.*" if p_index else f"*_BV{bv_id}*"
                else:
                    search_pattern = f"*_{bv_id}*"
                
                all_files = list(self.download_dir.glob(search_pattern))
                logger.info(f"搜索模式 {search_pattern} 匹配到 {len(all_files)} 个文件")
                
                # 过滤出最终文件（不含 .f 数字的临时文件）
                final_files = [f for f in all_files if not re.search(r'\.f\d+\.', f.name) and f.suffix in ['.mp4', '.mkv', '.webm']]
                
                if final_files:
                    # 如果是多P视频，选择对应的分P
                    if p_index:
                        p_pattern = f"_p{p_index}."
                        p_files = [f for f in final_files if p_pattern in f.name]
                        if p_files:
                            p_files.sort(key=lambda x: x.stat().st_size, reverse=True)
                            logger.info(f"B站视频下载完成（分P {p_index}）: {p_files[0].name}")
                            return str(p_files[0])
                    
                    final_files.sort(key=lambda x: x.stat().st_size, reverse=True)
                    logger.info(f"B站视频下载完成: {final_files[0].name}")
                    return str(final_files[0])
                
                # 返回最大的文件
                if all_files:
                    mp4_files = [f for f in all_files if f.suffix == '.mp4']
                    if mp4_files:
                        mp4_files.sort(key=lambda x: x.stat().st_size, reverse=True)
                        logger.info(f"B站视频下载完成: {mp4_files[0].name}")
                        return str(mp4_files[0])
            
            # 方法3：列出最近下载的文件
            recent_files = sorted(
                [f for f in self.download_dir.glob("*.mp4")],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )[:5]
            logger.info(f"最近下载的文件: {[f.name for f in recent_files]}")
            
            if recent_files:
                return str(recent_files[0])
            
            raise Exception("无法找到下载的文件")
        
        finally:
            self._progress_store.pop(task_id, None)
            # 清理临时 cookie 文件
            if "cookiefile" in options and os.path.exists(options["cookiefile"]):
                os.unlink(options["cookiefile"])
    
    def raw_to_video_info(self, raw_info: Dict[str, Any], url: str, platform: Platform) -> VideoInfo:
        """将 yt-dlp 返回的原始信息转换为 VideoInfo（B站专用）
        
        支持多P视频选集：
        - 如果是多P视频，entries 字段包含所有分P信息
        - 将分P信息转换为 formats，让用户选择下载哪个
        """
        formats = []
        entries = raw_info.get("entries", [])
        
        # 检测是否是多P视频
        if entries and len(entries) > 0:
            is_multi_part = len(entries) > 1
            if is_multi_part:
                logger.info(f"检测到多P视频，共 {len(entries)} 个分P")
            
            # 多P视频：将每个分P作为一个"格式"选项
            for idx, entry in enumerate(entries):
                part_num = idx + 1
                part_title = entry.get("title", f"第{part_num}P")
                part_duration = entry.get("duration", 0)
                
                # 获取该分P的最佳格式信息
                entry_formats = entry.get("formats", [])
                best_resolution = None
                best_filesize = None
                
                if entry_formats:
                    # 找最佳格式
                    for fmt in entry_formats:
                        if fmt.get("vcodec") != "none":
                            height = fmt.get("height")
                            if height:
                                if best_resolution is None or height > int(best_resolution.split('x')[1] if 'x' in str(best_resolution) else 0):
                                    best_resolution = f"{fmt.get('width', 0)}x{height}"
                                    best_filesize = fmt.get("filesize") or fmt.get("filesize_approx")
                            break
                
                quality_str = f"P{part_num} {part_title}"
                if part_duration:
                    mins, secs = divmod(int(part_duration), 60)
                    quality_str += f" ({mins}:{secs:02d})"
                if best_resolution:
                    quality_str += f" [{best_resolution}]"
                
                formats.append(VideoFormat(
                    format_id=f"p{part_num}",
                    ext="mp4",
                    resolution=best_resolution,
                    filesize=best_filesize,
                    vcodec="h264",
                    acodec="aac",
                    quality=quality_str,
                    is_audio_only=False,
                    is_video_only=False,
                    url=f"?p={part_num}",  # 用于标识分P
                ))
            
            # 处理封面 URL
            thumbnail = raw_info.get("thumbnail") or (entries[0].get("thumbnail") if entries else None)
            if thumbnail and thumbnail.startswith("http://"):
                thumbnail = "https://" + thumbnail[7:]
            
            # 计算总时长
            total_duration = sum(e.get("duration", 0) for e in entries)
            
            return VideoInfo(
                id=str(raw_info.get("id") or entries[0].get("id", "")),
                title=raw_info.get("title", entries[0].get("title", "未知标题") if entries else "未知标题"),
                description=raw_info.get("description"),
                thumbnail=thumbnail,
                duration=total_duration if is_multi_part else (entries[0].get("duration") if entries else 0),
                uploader=raw_info.get("uploader") or raw_info.get("channel") or (entries[0].get("uploader") if entries else None),
                uploader_id=raw_info.get("uploader_id") or (entries[0].get("uploader_id") if entries else None),
                upload_date=raw_info.get("upload_date") or (entries[0].get("upload_date") if entries else None),
                view_count=raw_info.get("view_count"),
                like_count=raw_info.get("like_count"),
                comment_count=raw_info.get("comment_count"),
                platform=platform,
                original_url=url,
                formats=formats,
                best_format=formats[0] if formats else None,
            )
        
        # 单视频处理
        for fmt in raw_info.get("formats", []):
            if fmt.get("vcodec") == "none" and fmt.get("acodec") == "none":
                continue
            
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")
            is_audio_only = fmt.get("vcodec") == "none"
            is_video_only = fmt.get("acodec") == "none"
            
            video_format = VideoFormat(
                format_id=fmt.get("format_id", ""),
                ext=fmt.get("ext", "mp4"),
                resolution=self._get_resolution(fmt),
                filesize=filesize,
                filesize_approx=fmt.get("filesize_approx"),
                vcodec=fmt.get("vcodec"),
                acodec=fmt.get("acodec"),
                fps=fmt.get("fps"),
                quality=fmt.get("format_note") or fmt.get("quality_label"),
                is_audio_only=is_audio_only,
                is_video_only=is_video_only,
            )
            formats.append(video_format)
        
        # 按分辨率排序
        def get_height(fmt: VideoFormat) -> int:
            if fmt.resolution:
                match = re.search(r'(\d+)$', fmt.resolution)
                if match:
                    return int(match.group(1))
            return 0
        
        formats.sort(key=get_height, reverse=True)
        
        best_format = formats[0] if formats else None
        
        if raw_info.get("format_id"):
            best_format = next(
                (f for f in formats if f.format_id == raw_info["format_id"]),
                best_format
            )
        
        # 处理封面 URL
        thumbnail = raw_info.get("thumbnail")
        if thumbnail and thumbnail.startswith("http://"):
            thumbnail = "https://" + thumbnail[7:]
        
        return VideoInfo(
            id=str(raw_info.get("id", "")),
            title=raw_info.get("title", "未知标题"),
            description=raw_info.get("description"),
            thumbnail=thumbnail,
            duration=raw_info.get("duration"),
            uploader=raw_info.get("uploader") or raw_info.get("channel"),
            uploader_id=raw_info.get("uploader_id"),
            upload_date=raw_info.get("upload_date"),
            view_count=raw_info.get("view_count"),
            like_count=raw_info.get("like_count"),
            comment_count=raw_info.get("comment_count"),
            platform=platform,
            original_url=url,
            formats=formats,
            best_format=best_format,
        )
    
    @staticmethod
    def _get_resolution(fmt: Dict) -> Optional[str]:
        """获取分辨率字符串"""
        width = fmt.get("width")
        height = fmt.get("height")
        if width and height:
            return f"{width}x{height}"
        if height:
            return f"{height}p"
        return None
