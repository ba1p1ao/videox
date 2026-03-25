"""
Bilibili 视频下载器
基于 yt-dlp 实现 B站视频下载
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
    - 支持多 P 视频下载
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
    
    def _build_expected_filename_pattern(self, video_title: str, video_id: str) -> str:
        """构建预期的文件名模式
        
        文件名格式：{title}_{id}.{ext}
        注意：B站ID已经包含BV前缀，如 BV1DVAgzNEcs
        """
        clean_title = self._sanitize_filename(video_title, max_length=80)
        # 构建 glob 模式
        return f"{clean_title}_{video_id}.*"
    
    def _build_bilibili_options(self, download: bool = False, format_id: Optional[str] = None,
                                quality: str = "best", audio_only: bool = False,
                                task_id: Optional[str] = None,
                                need_audio: bool = False) -> Dict[str, Any]:
        """构建 B站专用 yt-dlp 配置
        
        Args:
            need_audio: 当选择的格式是纯视频流时，是否需要自动添加音频流
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

        # B站专用 Headers（更完整，绕过 WAF）
        options["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

        # Cookie 支持（B站需要登录才能获取 1080p+）
        if self.cookies:
            # Cookie 字符串，转换为 Netscape 格式
            cookie_content = self._convert_cookie_to_netscape(self.cookies, ".bilibili.com")
            cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            cookie_file.write(cookie_content)
            cookie_file.close()
            options["cookiefile"] = cookie_file.name

        # 输出模板（B站ID已包含BV前缀，所以不需要额外添加）
        options["outtmpl"] = {
            "default": str(self.download_dir / "%(title).80s_%(id)s.%(ext)s"),
        }

        # 格式选择
        if audio_only:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        elif format_id:
            # 指定了格式ID，使用回退策略
            # 优先使用指定格式，如果不可用则回退到最佳格式
            if need_audio:
                # 纯视频格式，自动添加最佳音频流
                options["format"] = f"{format_id}+bestaudio/bestvideo+bestaudio/best"
                logger.info(f"使用格式: {format_id}+bestaudio（自动添加音频流，带回退）")
            else:
                # 格式已包含音频或是纯音频，带回退
                options["format"] = f"{format_id}/bestvideo+bestaudio/best"
                logger.info(f"使用格式: {format_id}（带回退到最佳格式）")
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
        """解析 B站视频信息"""
        # 处理 b23.tv 短链接
        if 'b23.tv' in url:
            url = self.resolve_short_url(url)
        
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
    
    async def download_video(self, url: str, quality: str = "best", 
                             format_id: Optional[str] = None,
                             audio_only: bool = False,
                             video_title: Optional[str] = None,
                             video_id: Optional[str] = None,
                             **kwargs) -> str:
        """下载 B站视频
        
        自动检测并处理音视频分离的情况：
        - 如果选择的格式是纯视频流（无音频），自动添加最佳音频流进行合并
        - 确保下载的视频始终包含音频
        
        Args:
            video_title: 视频标题（用于精确匹配下载文件）
            video_id: 视频ID（用于精确匹配下载文件）
        """
        # 处理 b23.tv 短链接
        if 'b23.tv' in url:
            url = self.resolve_short_url(url)
        
        task_id = f"bili_{os.urandom(4).hex()}"
        self._progress_store[task_id] = DownloadProgress(task_id)
        
        # 构建预期文件名模式（如果提供了标题和ID）
        expected_pattern = None
        if video_title and video_id:
            expected_pattern = self._build_expected_filename_pattern(video_title, video_id)
            logger.info(f"预期文件名模式: {expected_pattern}")
        
        # 检查指定格式是否需要添加音频流
        need_audio = False
        if format_id and not audio_only:
            # 先解析视频信息，获取格式详情
            try:
                video_info = await self.parse_video_info(url)
                # 如果没有提供 video_id，从解析结果中获取
                if not video_id:
                    video_id = video_info.id
                    if video_id:
                        expected_pattern = self._build_expected_filename_pattern(
                            video_title or video_info.title, video_id
                        )
                        logger.info(f"从解析结果获取ID，预期文件名模式: {expected_pattern}")
                
                for fmt in video_info.formats:
                    if fmt.format_id == format_id:
                        # 检查是否是纯视频流（有视频无音频）
                        vcodec = fmt.vcodec or "none"
                        acodec = fmt.acodec or "none"
                        has_video = vcodec != "none"
                        has_audio = acodec != "none"
                        if has_video and not has_audio:
                            need_audio = True
                            logger.info(f"格式 {format_id} 是纯视频流，将自动添加音频流进行合并")
                        break
            except Exception as e:
                logger.warning(f"解析格式信息失败，使用默认格式选择: {e}")
        
        options = self._build_bilibili_options(
            download=True,
            format_id=format_id,
            quality=quality,
            audio_only=audio_only,
            task_id=task_id,
            need_audio=need_audio,
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
            
            # 方法2：通过预期文件名模式匹配
            if expected_pattern:
                matched_files = list(self.download_dir.glob(expected_pattern))
                logger.info(f"模式 {expected_pattern} 匹配到 {len(matched_files)} 个文件")
                if matched_files:
                    # 选择最大的文件（合并后的最终文件）
                    matched_files.sort(key=lambda x: x.stat().st_size, reverse=True)
                    logger.info(f"B站视频下载完成（通过文件名模式匹配）: {matched_files[0].name}")
                    return str(matched_files[0])
            
            # 方法3：通过 URL 中的 BV 号匹配（包括合并后的文件）
            bv_match = re.search(r'(BV[a-zA-Z0-9]+)', url)
            if bv_match:
                bv_id = bv_match.group(1)
                # 匹配 *_BV{bv_id}*.mp4 或 *.mkv 等（排除 .f 数字 的临时文件）
                all_files = list(self.download_dir.glob(f"*_BV{bv_id}*"))
                logger.info(f"BV号匹配到 {len(all_files)} 个文件: {[f.name for f in all_files]}")
                
                # 过滤出最终文件（不含 .f 数字的文件，这些是合并后的文件）
                final_files = [f for f in all_files if not re.search(r'\.f\d+\.', f.name)]
                if final_files:
                    final_files.sort(key=lambda x: x.stat().st_size, reverse=True)
                    logger.info(f"B站视频下载完成（通过BV号匹配最终文件）: {final_files[0].name}")
                    return str(final_files[0])
                
                # 如果没有合并后的文件，返回最大的文件
                if all_files:
                    all_files.sort(key=lambda x: x.stat().st_size, reverse=True)
                    logger.info(f"B站视频下载完成（返回最大文件）: {all_files[0].name}")
                    return str(all_files[0])
            
            # 方法4：列出所有最近下载的文件
            recent_files = sorted(
                self.download_dir.glob("*"),
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )[:5]
            logger.info(f"最近下载的文件: {[f.name for f in recent_files]}")
            
            raise Exception("无法找到下载的文件")
        
        finally:
            self._progress_store.pop(task_id, None)
            # 清理临时 cookie 文件
            if "cookiefile" in options and os.path.exists(options["cookiefile"]):
                os.unlink(options["cookiefile"])
    
    def raw_to_video_info(self, raw_info: Dict[str, Any], url: str, platform: Platform) -> VideoInfo:
        """将 yt-dlp 返回的原始信息转换为 VideoInfo（B站专用）"""
        formats = []
        
        for fmt in raw_info.get("formats", []):
            # 跳过无效格式
            if fmt.get("vcodec") == "none" and fmt.get("acodec") == "none":
                continue
            
            # B站格式处理：文件大小可能使用 filesize_approx
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")
            
            # 判断是否为纯音频/纯视频
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
        
        # 最佳格式
        best_format = formats[0] if formats else None
        
        # 从 formats 中提取信息
        if raw_info.get("format_id"):
            best_format = next(
                (f for f in formats if f.format_id == raw_info["format_id"]),
                best_format
            )
        
        # 处理封面 URL（将 HTTP 转换为 HTTPS，避免混合内容问题）
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