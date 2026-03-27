"""
抖音视频下载器
基于自建 API 客户端实现无水印视频下载
"""
import os
import sys
import re
import json
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path
import sqlite3
import tempfile
import shutil

from loguru import logger

from ..base import BaseDownloader
from ..platform_handler import Platform
from ...models.video import VideoInfo, VideoFormat
from .api_client import DouyinAPIClient

# 检测 API 客户端是否可用
try:
    DOUYIN_API_AVAILABLE = True
except ImportError:
    DOUYIN_API_AVAILABLE = False
    logger.warning("抖音 API 客户端未正确加载")


class DouyinDownloader(BaseDownloader):
    """抖音专用下载器
    
    功能：
    - 无水印视频下载
    - 图文作品下载
    - 短链接解析
    - 自动从浏览器/cookies.json 文件读取 Cookie
    - 支持 1080p 高清视频
    """
    
    platform = Platform.DOUYIN
    
    URL_PATTERNS = [
        r'douyin\.com',
        r'iesdouyin\.com',
    ]
    
    def __init__(self, download_dir: Optional[Path] = None, proxy: Optional[str] = None, 
                 cookies: Optional[str] = None):
        super().__init__(download_dir, proxy)
        self.cookies = self._parse_cookies(cookies)
    
    # ==================== Cookie 管理 ====================
    
    @staticmethod
    def _safe_int(value, default=0) -> int:
        """安全地转换为整数"""
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            if value.strip() == '':
                return default
            try:
                return int(value)
            except ValueError:
                return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def _get_cookie_file_paths() -> List[Path]:
        """获取 Cookie 文件路径列表"""
        # backend/config/douyin_cookies.json 为主要路径
        config_dir = Path(__file__).parent.parent.parent.parent / "config"
        
        return [
            config_dir / "douyin_cookies.json",
            config_dir / "cookies.json",
        ]
    
    def _parse_cookies(self, cookies_str: Optional[str]) -> Dict[str, str]:
        """解析 cookie 字符串为字典"""
        if cookies_str:
            cookies = {}
            for item in cookies_str.split(';'):
                item = item.strip()
                if '=' in item:
                    name, value = item.split('=', 1)
                    cookies[name.strip()] = value.strip()
            if cookies:
                return cookies
        
        return self._read_cookies_auto()
    
    def _read_cookies_auto(self, run_fetcher: bool = False) -> Dict[str, str]:
        """自动从多个来源读取抖音 Cookie
        
        同时尝试多个浏览器，优先返回有登录凭证(sessionid)的 Cookie
        """
        all_cookies = []  # 存储 (cookies, has_login, source) 元组
        
        # 1. 尝试从 cookies.json 文件读取
        cookies = self._read_cookies_from_file()
        if cookies:
            has_login = 'sessionid' in cookies and cookies.get('sessionid')
            all_cookies.append((cookies, has_login, 'cookies.json'))
            logger.debug(f"从 cookies.json 读取到 {len(cookies)} 个 Cookie, 登录状态: {has_login}")
        
        # 2. 尝试从 Firefox 浏览器读取
        cookies = self._read_cookies_from_firefox()
        if cookies:
            has_login = 'sessionid' in cookies and cookies.get('sessionid')
            all_cookies.append((cookies, has_login, 'Firefox'))
            logger.debug(f"从 Firefox 读取到 {len(cookies)} 个 Cookie, 登录状态: {has_login}")
        
        # 3. 尝试从 Chrome 浏览器读取
        cookies = self._read_cookies_from_chrome()
        if cookies:
            has_login = 'sessionid' in cookies and cookies.get('sessionid')
            all_cookies.append((cookies, has_login, 'Chrome'))
            logger.debug(f"从 Chrome 读取到 {len(cookies)} 个 Cookie, 登录状态: {has_login}")
        
        # 4. 尝试从 Edge 浏览器读取
        cookies = self._read_cookies_from_edge()
        if cookies:
            has_login = 'sessionid' in cookies and cookies.get('sessionid')
            all_cookies.append((cookies, has_login, 'Edge'))
            logger.debug(f"从 Edge 读取到 {len(cookies)} 个 Cookie, 登录状态: {has_login}")
        
        # 5. 优先返回有登录凭证的 Cookie
        for cookies, has_login, source in all_cookies:
            if has_login and 'ttwid' in cookies:
                logger.info(f"从 {source} 读取到 {len(cookies)} 个抖音 Cookie (已登录)")
                return cookies
        
        # 6. 如果都没有登录，返回有 ttwid 的第一个
        for cookies, has_login, source in all_cookies:
            if 'ttwid' in cookies:
                logger.info(f"从 {source} 读取到 {len(cookies)} 个抖音 Cookie (未登录)")
                return cookies
        
        # 7. 运行 cookie_fetcher
        if run_fetcher:
            logger.info("未找到有效 Cookie，自动启动浏览器获取...")
            cookies = self._run_cookie_fetcher()
            if cookies and 'ttwid' in cookies:
                return cookies
        
        logger.warning("未找到有效抖音 Cookie")
        return {}
    
    def _read_cookies_from_file(self) -> Dict[str, str]:
        """从 cookies.json 文件读取 Cookie"""
        for cookie_path in self._get_cookie_file_paths():
            if cookie_path.exists():
                try:
                    with open(cookie_path, 'r', encoding='utf-8') as f:
                        cookies = json.load(f)
                    if isinstance(cookies, dict) and cookies:
                        logger.debug(f"从 {cookie_path} 读取到 Cookie")
                        return cookies
                except Exception as e:
                    logger.debug(f"读取 {cookie_path} 失败: {e}")
        return {}
    
    def _read_cookies_from_firefox(self) -> Dict[str, str]:
        """从 Firefox 读取抖音 cookie"""
        firefox_profiles = [
            os.path.expanduser("~/snap/firefox/common/.mozilla/firefox"),
            os.path.expanduser("~/.mozilla/firefox"),
            os.path.expanduser("~/.var/app/org.mozilla.firefox/.mozilla/firefox"),
        ]
        
        for profiles_dir in firefox_profiles:
            if not os.path.isdir(profiles_dir):
                continue
            for item in os.listdir(profiles_dir):
                if item.endswith('.default') or item.endswith('.default-release'):
                    profile_path = os.path.join(profiles_dir, item)
                    cookies_file = os.path.join(profile_path, "cookies.sqlite")
                    if os.path.exists(cookies_file):
                        try:
                            temp_cookies = os.path.join(tempfile.gettempdir(), "firefox_douyin_cookies.sqlite")
                            shutil.copy2(cookies_file, temp_cookies)
                            
                            conn = sqlite3.connect(temp_cookies)
                            cursor = conn.cursor()
                            cursor.execute(
                                "SELECT name, value FROM moz_cookies WHERE host LIKE '%douyin%'"
                            )
                            cookies = {name: value for name, value in cursor.fetchall()}
                            conn.close()
                            os.unlink(temp_cookies)
                            
                            if cookies:
                                return cookies
                        except Exception as e:
                            logger.debug(f"从 Firefox 读取 cookie 失败: {e}")
        return {}
    
    def _read_cookies_from_chrome(self) -> Dict[str, str]:
        """从 Chrome 读取抖音 cookie"""
        chrome_paths = [
            os.path.expanduser("~/.config/google-chrome/Default/Cookies"),
            os.path.expanduser("~/.config/google-chrome/Profile 1/Cookies"),
            os.path.expanduser("~/.config/chromium/Default/Cookies"),
        ]
        
        for cookies_file in chrome_paths:
            if os.path.exists(cookies_file):
                try:
                    temp_cookies = os.path.join(tempfile.gettempdir(), "chrome_douyin_cookies.sqlite")
                    shutil.copy2(cookies_file, temp_cookies)
                    
                    conn = sqlite3.connect(temp_cookies)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT name, encrypted_value, host_key FROM cookies WHERE host_key LIKE '%douyin%'"
                    )
                    cookies = {}
                    for name, encrypted_value, host_key in cursor.fetchall():
                        if encrypted_value[:3] not in [b'v10', b'v11']:
                            try:
                                cookies[name] = encrypted_value.decode('utf-8')
                            except:
                                pass
                    conn.close()
                    os.unlink(temp_cookies)
                    
                    if cookies:
                        return cookies
                except Exception as e:
                    logger.debug(f"从 Chrome 读取 cookie 失败: {e}")
        return {}
    
    def _read_cookies_from_edge(self) -> Dict[str, str]:
        """从 Edge 读取抖音 cookie"""
        edge_paths = [
            os.path.expanduser("~/.config/microsoft-edge/Default/Cookies"),
        ]
        
        for cookies_file in edge_paths:
            if os.path.exists(cookies_file):
                try:
                    temp_cookies = os.path.join(tempfile.gettempdir(), "edge_douyin_cookies.sqlite")
                    shutil.copy2(cookies_file, temp_cookies)
                    
                    conn = sqlite3.connect(temp_cookies)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%douyin%'"
                    )
                    cookies = {}
                    for name, value in cursor.fetchall():
                        if value and not name.startswith('_'):
                            try:
                                cookies[name] = value.decode('utf-8') if isinstance(value, bytes) else value
                            except:
                                pass
                    conn.close()
                    os.unlink(temp_cookies)
                    
                    if cookies:
                        return cookies
                except Exception as e:
                    logger.debug(f"从 Edge 读取 cookie 失败: {e}")
        return {}
    
    def _run_cookie_fetcher(self) -> Dict[str, str]:
        """运行 cookie_fetcher 自动获取 Cookie"""
        import subprocess
        
        # Cookie 保存路径
        config_dir = Path(__file__).parent.parent.parent.parent / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        output_path = config_dir / "douyin_cookies.json"
        
        # cookie_fetcher.py 路径
        cookie_fetcher_path = Path(__file__).parent / "cookie_fetcher.py"
        
        if not cookie_fetcher_path.exists():
            logger.error("未找到 cookie_fetcher.py")
            return {}
        
        logger.info("=" * 60)
        logger.info("正在启动浏览器获取抖音 Cookie...")
        logger.info("请在弹出的浏览器中登录抖音，登录成功后回到终端按 Enter 继续")
        logger.info("=" * 60)
        
        try:
            result = subprocess.run(
                [sys.executable, "-m", "tools.cookie_fetcher", "--browser", "firefox", "--output", str(output_path)],
                cwd=str(cookie_fetcher_path.parent.parent),
                capture_output=False,
                text=True,
            )
            
            if result.returncode == 0 and output_path.exists():
                with open(output_path, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                
                if cookies and 'ttwid' in cookies:
                    logger.info(f"成功获取 {len(cookies)} 个抖音 Cookie")
                    return cookies
        except Exception as e:
            logger.error(f"运行 cookie_fetcher 失败: {e}")
        
        return {}
    
    # ==================== 视频解析和下载 ====================
    
    async def _resolve_url(self, url: str, client: DouyinAPIClient) -> str:
        """解析短链接，返回真实 URL"""
        if 'v.douyin.com' in url or 'iesdouyin.com' in url:
            real_url = await client.resolve_short_url(url)
            if real_url:
                logger.info(f"短链接解析: {url} -> {real_url}")
                return real_url
        return url
    
    async def parse_video_info(self, url: str, **kwargs) -> VideoInfo:
        """解析抖音视频信息"""
        if not DOUYIN_API_AVAILABLE:
            raise Exception("抖音 API 客户端未正确加载")
        
        import aiohttp
        import base64
        
        # 解析短链接（只需一次）
        async with DouyinAPIClient(cookies=self.cookies, proxy=self.proxy) as client:
            real_url = await self._resolve_url(url, client)
            aweme_id = DouyinAPIClient.extract_aweme_id(real_url)
        
        if not aweme_id:
            raise Exception(f"无法从 URL 提取视频 ID: {real_url}")
        
        logger.info(f"解析抖音视频: aweme_id={aweme_id}")
        
        # 尝试解析（最多重试 2 次）
        aweme_detail = None
        max_attempts = 2
        
        for attempt in range(max_attempts):
            # 每次尝试创建新的客户端实例，以获取新的签名参数
            async with DouyinAPIClient(cookies=self.cookies, proxy=self.proxy) as client:
                # 强制刷新 msToken（清除缓存的 token）
                client._ms_token = None
                
                # 获取视频详情
                aweme_detail = await client.get_video_detail(aweme_id)
                
                if aweme_detail:
                    break
                
                if attempt < max_attempts - 1:
                    logger.info(f"API 解析失败，刷新签名参数后重试 (尝试 {attempt + 2}/{max_attempts})...")
                    await asyncio.sleep(1)
        
        # 如果 API 仍然失败，尝试从网页解析
        if not aweme_detail:
            logger.info("API 解析失败，尝试从网页解析...")
            async with DouyinAPIClient(cookies=self.cookies, proxy=self.proxy) as client:
                aweme_detail = await self._parse_from_web(real_url, aweme_id)
        
        if not aweme_detail:
            raise Exception(f"获取视频详情失败: aweme_id={aweme_id}")
        
        # 获取 1080p 文件大小
        filesize_1080p = None
        video = aweme_detail.get("video", {})
        if video and video.get("height", 0) >= 1080:
            try:
                async with DouyinAPIClient(cookies=self.cookies, proxy=self.proxy) as client:
                    filesize_1080p = await client.get_1080p_filesize(aweme_detail)
                    if filesize_1080p:
                        logger.info(f"获取到 1080p 文件大小: {filesize_1080p} bytes")
            except Exception as e:
                logger.debug(f"获取 1080p 文件大小失败: {e}")
        
        video_info = self._to_video_info(aweme_detail, url, filesize_1080p)
        
        # 下载封面并转为 base64（解决防盗链问题）
        # 获取所有可用的封面 URL，用于失败时的回退
        all_cover_urls = aweme_detail.get('_all_cover_urls', [])
        if video_info.thumbnail and not video_info.thumbnail.startswith('data:'):
            # 确保当前 thumbnail 在列表中
            if video_info.thumbnail not in all_cover_urls:
                all_cover_urls.insert(0, video_info.thumbnail)
            
            # 尝试所有封面 URL，直到成功
            for idx, cover_url in enumerate(all_cover_urls):
                try:
                    thumbnail_base64 = await self._download_thumbnail_as_base64(cover_url)
                    if thumbnail_base64:
                        video_info.thumbnail = thumbnail_base64
                        logger.debug(f"封面已转为 base64 (使用第 {idx + 1} 个 URL)")
                        break
                    else:
                        logger.debug(f"封面 URL {idx + 1} 下载失败，尝试下一个...")
                except Exception as e:
                    logger.debug(f"下载封面 URL {idx + 1} 失败: {e}")

            # 如果下载失败，尝试使用 playwright 渲染页面获取封面
            if not video_info.thumbnail.startswith("data:"):
                try:
                    from playwright.async_api import async_playwright
                    logger.info("尝试使用 playwright 获取封面...")
                    async with async_playwright() as p:
                        # 尝试使用已登录的浏览器上下文
                        browser = await p.chromium.launch(headless=True)
                        
                        # 构建完整的 cookie 列表（包括所有来源的 cookie）
                        all_cookies = {}
                        # 首先添加从文件读取的 cookie
                        if self.cookies:
                            all_cookies.update(self.cookies)
                        
                        # 转换为 playwright 格式
                        cookie_list = []
                        for k, v in all_cookies.items():
                            cookie_list.append({
                                "name": k,
                                "value": str(v),
                                "domain": ".douyin.com",
                                "path": "/"
                            })
                        
                        context = await browser.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        )
                        if cookie_list:
                            await context.add_cookies(cookie_list)
                            logger.debug(f"添加 {len(cookie_list)} 个 cookie 到 playwright")
                        page = await context.new_page()
                        try:
                            await page.goto(real_url, wait_until="domcontentloaded", timeout=30000)
                            await page.wait_for_timeout(5000)
                            
                            # 尝试多种方式获取封面
                            thumb = await page.evaluate("""
                                async () => {
                                    // 方式1: 视频封面
                                    const v = document.querySelector("video[poster]");
                                    if (v && v.poster) {
                                        try {
                                            const r = await fetch(v.poster);
                                            const b = await r.blob();
                                            const result = await new Promise((res) => {
                                                const reader = new FileReader();
                                                reader.onloadend = () => res(reader.result);
                                                reader.onerror = () => res(null);
                                                reader.readAsDataURL(b);
                                            });
                                            if (result) return result;
                                        } catch(e) {}
                                    }
                                    
                                    // 方式2: og:image meta 标签
                                    const ogImg = document.querySelector('meta[property="og:image"]');
                                    if (ogImg && ogImg.content) {
                                        try {
                                            const r = await fetch(ogImg.content);
                                            const b = await r.blob();
                                            const result = await new Promise((res) => {
                                                const reader = new FileReader();
                                                reader.onloadend = () => res(reader.result);
                                                reader.onerror = () => res(null);
                                                reader.readAsDataURL(b);
                                            });
                                            if (result) return result;
                                        } catch(e) {}
                                    }
                                    
                                    // 方式3: 页面上的大图
                                    const imgs = document.querySelectorAll('img');
                                    for (const img of imgs) {
                                        if (img.naturalWidth > 200 && img.naturalHeight > 200 && 
                                            img.src && img.src.includes('douyinpic')) {
                                            try {
                                                const r = await fetch(img.src);
                                                const b = await r.blob();
                                                const result = await new Promise((res) => {
                                                    const reader = new FileReader();
                                                    reader.onloadend = () => res(reader.result);
                                                    reader.onerror = () => res(null);
                                                    reader.readAsDataURL(b);
                                                });
                                                if (result) return result;
                                            } catch(e) {}
                                        }
                                    }
                                    
                                    return null;
                                }
                            """)
                            if thumb:
                                video_info.thumbnail = thumb
                                logger.info("playwright 获取封面成功")
                            else:
                                logger.warning("playwright 未能获取到封面")
                        finally:
                            await browser.close()
                except Exception as e:
                    logger.warning(f"playwright 获取封面失败: {e}")
        
        # 处理图文作品：下载图片到本地
        is_gallery = aweme_detail.get("image_post_info") or aweme_detail.get("images")
        if is_gallery and video_info.formats:
            images = aweme_detail.get("images") or aweme_detail.get("image_post_info", {}).get("images", [])
            if images:
                logger.info(f"开始下载图文图片到本地: {len(images)} 张")
                local_images = await self._download_gallery_images(aweme_id, images)
                
                # 更新 formats 中的 URL 为本地路径
                for i, fmt in enumerate(video_info.formats):
                    if i < len(local_images):
                        fmt.url = local_images[i]["url"]
                        if local_images[i].get("width") and local_images[i].get("height"):
                            fmt.resolution = f"{local_images[i]['width']}x{local_images[i]['height']}"
        
        return video_info
    
    async def _download_thumbnail_as_base64(self, thumbnail_url: str) -> Optional[str]:
        """下载封面并转为 base64"""
        import aiohttp
        import base64
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        
        try:
            async with aiohttp.ClientSession(cookies=self.cookies) as session:
                async with session.get(thumbnail_url, headers=headers, proxy=self.proxy, timeout=15) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', 'image/jpeg')
                        data = await response.read()
                        b64_data = base64.b64encode(data).decode('utf-8')
                        return f"data:{content_type};base64,{b64_data}"
                    else:
                        logger.debug(f"下载封面失败: HTTP {response.status}")
        except Exception as e:
            logger.debug(f"下载封面异常: {e}")
        
        return None
    
    async def _download_gallery_images(self, aweme_id: str, images: List[Dict]) -> List[Dict]:
        """下载图文作品图片到本地，返回本地静态文件 URL"""
        import aiohttp
        import base64
        import hashlib
        
        # 图片存储目录
        images_dir = self.download_dir / "images" / "douyin" / aweme_id
        images_dir.mkdir(parents=True, exist_ok=True)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        
        result = []
        
        async with aiohttp.ClientSession() as session:
            for idx, img in enumerate(images):
                # 获取图片 URL
                img_url = None
                base64_data = None
                
                if isinstance(img, dict):
                    # 优先使用已有的 base64 数据
                    if img.get('base64'):
                        base64_data = img['base64']
                    else:
                        # 从各种字段提取 URL
                        for field in ["url_list", "urlList"]:
                            url_list = img.get(field, [])
                            if url_list and isinstance(url_list, list):
                                img_url = url_list[0]
                                break
                        
                        if not img_url:
                            for field in ["display_image", "owner_watermark_image", "download_url", "url"]:
                                field_data = img.get(field, {})
                                if isinstance(field_data, dict):
                                    url_list = field_data.get("url_list") or field_data.get("urlList", [])
                                    if url_list:
                                        img_url = url_list[0]
                                        break
                
                if not img_url and not base64_data:
                    continue
                
                # 生成文件名
                ext = ".jpg"
                if img_url:
                    if ".png" in img_url.lower():
                        ext = ".png"
                    elif ".webp" in img_url.lower():
                        ext = ".webp"
                
                filename = f"{idx + 1:02d}{ext}"
                filepath = images_dir / filename
                
                try:
                    # 下载或保存图片
                    if base64_data:
                        # 从 base64 解码
                        if base64_data.startswith('data:'):
                            # 解析 data URL
                            header, data = base64_data.split(',', 1)
                            if 'png' in header:
                                ext = '.png'
                                filename = f"{idx + 1:02d}{ext}"
                                filepath = images_dir / filename
                            elif 'webp' in header:
                                ext = '.webp'
                                filename = f"{idx + 1:02d}{ext}"
                                filepath = images_dir / filename
                            img_data = base64.b64decode(data)
                        else:
                            img_data = base64.b64decode(base64_data)
                        
                        with open(filepath, 'wb') as f:
                            f.write(img_data)
                    else:
                        # 从 URL 下载
                        async with session.get(img_url, headers=headers, proxy=self.proxy, timeout=30) as response:
                            if response.status == 200:
                                img_data = await response.read()
                                with open(filepath, 'wb') as f:
                                    f.write(img_data)
                            else:
                                logger.warning(f"下载图片 {idx + 1} 失败: HTTP {response.status}")
                                continue
                    
                    # 获取尺寸
                    width = img.get("width") if isinstance(img, dict) else None
                    height = img.get("height") if isinstance(img, dict) else None
                    
                    result.append({
                        "url": f"/static/images/douyin/{aweme_id}/{filename}",
                        "width": width,
                        "height": height,
                    })
                    logger.debug(f"已保存图片 {idx + 1}/{len(images)}: {filename}")
                    
                except Exception as e:
                    logger.warning(f"保存图片 {idx + 1} 失败: {e}")
                    continue
        
        logger.info(f"已保存 {len(result)}/{len(images)} 张图片到 {images_dir}")
        return result
    
    async def _parse_from_web(self, url: str, aweme_id: str) -> Optional[Dict[str, Any]]:
        """从网页解析抖音内容（API 失败时的备用方案）"""
        import aiohttp
        import re
        import json
        from urllib.parse import unquote
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.douyin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, cookies=self.cookies, proxy=self.proxy, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"网页请求失败: HTTP {response.status}")
                        return None
                    
                    html = await response.text()
                    
                    # 方法1: 查找 self.__pace_f.push([1,"..."]) 中的数据
                    matches = re.findall(r'self\.__pace_f\.push\(\[1,"(.+?)"\]\)', html)
                    
                    for m in matches:
                        try:
                            decoded = unquote(m)
                            if 'awemeId' in decoded or 'aweme' in decoded:
                                # 处理转义字符
                                decoded = decoded.replace('\\"', '"')
                                decoded = decoded.replace('\\/', '/')
                                decoded = re.sub(r'"\$undefined"', 'null', decoded)
                                
                                # 尝试找到 JSON 数组的开始
                                json_start = decoded.find('[{')
                                if json_start == -1:
                                    json_start = decoded.find('{"')
                                
                                if json_start != -1:
                                    json_str = decoded[json_start:]
                                    
                                    try:
                                        data = json.loads(json_str)
                                        result = self._extract_aweme_from_data(data, aweme_id)
                                        if result:
                                            logger.info(f"从网页解析成功 (方法1)")
                                            return result
                                    except json.JSONDecodeError:
                                        # 尝试找到一个完整的 JSON 对象
                                        brace_count = 0
                                        json_end = 0
                                        for i, c in enumerate(json_str):
                                            if c == '{':
                                                brace_count += 1
                                            elif c == '}':
                                                brace_count -= 1
                                                if brace_count == 0:
                                                    json_end = i + 1
                                                    break
                                        
                                        if json_end > 0:
                                            try:
                                                data = json.loads(json_str[:json_end])
                                                result = self._extract_aweme_from_data(data, aweme_id)
                                                if result:
                                                    logger.info(f"从网页解析成功 (方法1-修正)")
                                                    return result
                                            except json.JSONDecodeError:
                                                pass
                        except Exception as e:
                            logger.debug(f"方法1解析失败: {e}")
                            continue
                    
                    logger.warning(f"网页解析未能找到有效数据，尝试使用 playwright 渲染...")
                    return await self._parse_with_playwright(url, aweme_id)
                    
        except Exception as e:
            logger.error(f"网页解析异常: {e}")
            return await self._parse_with_playwright(url, aweme_id)
    
    async def _parse_with_playwright(self, url: str, aweme_id: str) -> Optional[Dict[str, Any]]:
        """使用 playwright 渲染页面并提取数据"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("playwright 未安装，无法渲染页面")
            return None
        
        logger.info(f"使用 playwright 渲染页面: {url}")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                
                # 添加 cookies
                if self.cookies:
                    cookie_list = []
                    for name, value in self.cookies.items():
                        cookie_list.append({
                            "name": name,
                            "value": str(value),
                            "domain": ".douyin.com",
                            "path": "/",
                        })
                    if cookie_list:
                        await context.add_cookies(cookie_list)
                
                page = await context.new_page()
                
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    
                    # 等待图片元素出现
                    try:
                        await page.wait_for_selector('img[src*="tos-cn-i"]', timeout=5000)
                    except Exception:
                        pass
                    
                    # 等待图片加载完成
                    await page.wait_for_timeout(4000)
                    
                    # 获取页面内容
                    content = await page.content()
                    
                    # 尝试从页面中提取数据
                    result = await self._extract_data_from_rendered_page(page, aweme_id, content)
                    
                    if result:
                        logger.info("从 playwright 渲染页面提取数据成功")
                        return result
                    
                finally:
                    await browser.close()
                    
        except Exception as e:
            logger.error(f"playwright 渲染失败: {e}")
            
        return None
    
    async def _extract_data_from_rendered_page(self, page, aweme_id: str, content: str) -> Optional[Dict[str, Any]]:
        """从渲染后的页面提取数据"""
        import re
        import json
        
        # 方法1: 从 __RENDER_DATA__ 中提取
        try:
            render_data = await page.evaluate("() => window.__RENDER_DATA__")
            if render_data:
                result = self._extract_aweme_from_data(render_data, aweme_id)
                if result:
                    return result
        except Exception:
            pass
        
        # 方法2: 从 __INITIAL_STATE__ 中提取
        try:
            initial_state = await page.evaluate("() => window.__INITIAL_STATE__")
            if initial_state:
                result = self._extract_aweme_from_data(initial_state, aweme_id)
                if result:
                    return result
        except Exception:
            pass
        
        # 方法3: 从页面标题提取描述
        try:
            title = await page.title()
            # 标题格式: "描述 - 抖音"
            if title and ' - 抖音' in title:
                desc = title.replace(' - 抖音', '').strip()
            else:
                desc = title or ""
            
            # 只获取图文内容区域的图片链接
            # 使用更通用的逻辑，不依赖特定 CDN 标识
            images_data = await page.evaluate('''
                async () => {
                    // 辅助函数：判断是否为非内容图片（头像、表情等）
                    const isNonContentImage = (src, width, height) => {
                        const srcLower = src.toLowerCase();
                        // 排除头像相关
                        if (srcLower.includes('avatar') || 
                            srcLower.includes('aweme-avatar') || 
                            srcLower.includes('s=profile') ||
                            srcLower.includes('/user/') ||
                            srcLower.includes('user-avatar')) {
                            return true;
                        }
                        // 排除太小的图片（表情包、图标等，通常小于 100px）
                        if (width > 0 && height > 0 && (width < 100 || height < 100)) {
                            return true;
                        }
                        return false;
                    };
                    
                    // 第一步：收集所有候选图片及其位置信息
                    const allImgs = document.querySelectorAll('img');
                    const candidates = [];
                    
                    for (const img of allImgs) {
                        const src = img.src || '';
                        // 只处理抖音图片 CDN
                        if (!src.includes('douyinpic.com') && !src.includes('bytedance.com') && !src.includes('byteimg.com')) continue;
                        
                        const rect = img.getBoundingClientRect();
                        const displayWidth = rect.width;
                        const displayHeight = rect.height;
                        
                        // 跳过非内容图片
                        if (isNonContentImage(src, displayWidth, displayHeight)) continue;
                        
                        candidates.push({
                            element: img,
                            src: src.split('~')[0],
                            x: rect.x,
                            y: rect.y,
                            width: displayWidth,
                            height: displayHeight,
                            naturalWidth: img.naturalWidth || 0,
                            naturalHeight: img.naturalHeight || 0
                        });
                    }
                    
                    if (candidates.length === 0) return [];
                    
                    // 第二步：找到图片最密集的父容器（内容区域）
                    const containerCount = new Map();
                    
                    for (const cand of candidates) {
                        let parent = cand.element.parentElement;
                        for (let i = 0; i < 5 && parent; i++) {
                            if (!containerCount.has(parent)) {
                                containerCount.set(parent, []);
                            }
                            if (!containerCount.get(parent).includes(cand)) {
                                containerCount.get(parent).push(cand);
                            }
                            parent = parent.parentElement;
                        }
                    }
                    
                    // 第三步：找到包含最多图片的容器
                    let bestContainer = null;
                    let maxCount = 0;
                    
                    for (const [container, imgs] of containerCount) {
                        if (imgs.length > maxCount) {
                            maxCount = imgs.length;
                            bestContainer = container;
                        }
                    }
                    
                    // 第四步：从最佳容器获取图片
                    const seenSrc = new Set();
                    const seenBase64 = new Set();
                    const fetchTasks = [];
                    
                    if (bestContainer) {
                        const containerImgs = bestContainer.querySelectorAll('img');
                        
                        for (const img of containerImgs) {
                            const src = img.src || '';
                            // 只处理抖音图片 CDN
                            if (!src.includes('douyinpic.com') && !src.includes('bytedance.com') && !src.includes('byteimg.com')) continue;
                            
                            const rect = img.getBoundingClientRect();
                            const displayWidth = rect.width;
                            const displayHeight = rect.height;
                            
                            // 跳过非内容图片
                            if (isNonContentImage(src, displayWidth, displayHeight)) continue;
                            
                            const cleanSrc = src.split('~')[0];
                            if (seenSrc.has(cleanSrc)) continue;
                            seenSrc.add(cleanSrc);
                            
                            const naturalWidth = img.naturalWidth || 0;
                            const naturalHeight = img.naturalHeight || 0;
                            
                            fetchTasks.push(
                                fetch(src)
                                    .then(r => r.blob())
                                    .then(blob => new Promise((resolve, reject) => {
                                        const reader = new FileReader();
                                        reader.onloadend = () => resolve({
                                            url: cleanSrc,
                                            base64: reader.result,
                                            width: naturalWidth || displayWidth,
                                            height: naturalHeight || displayHeight
                                        });
                                        reader.onerror = reject;
                                        reader.readAsDataURL(blob);
                                    }))
                                    .catch(() => null)
                            );
                        }
                    }
                    
                    const results = (await Promise.all(fetchTasks)).filter(r => r !== null);
                    
                    // 第五步：通过 base64 内容去重
                    const finalResults = [];
                    for (const r of results) {
                        if (!seenBase64.has(r.base64)) {
                            seenBase64.add(r.base64);
                            finalResults.push(r);
                        }
                    }
                    
                    // 第六步：再次过滤太小的图片（可能是漏网的表情包）
                    return finalResults.filter(r => r.width >= 100 && r.height >= 100).slice(0, 30);
                }
            ''')
            
            # 直接使用获取到的图片
            
            # 构建图片列表
            final_images = []
            for img in images_data:
                final_images.append({
                    'url_list': [img['url']],
                    'base64': img.get('base64'),  # 传递 base64 数据
                    'width': img.get('width'),
                    'height': img.get('height'),
                })
            
            # 尝试获取作者名
            author_name = "未知用户"
            try:
                # 尝试多种选择器
                author_selectors = [
                    '[data-e2e="video-author-nickname"]',
                    '.author-nickname',
                    '[class*="author"] [class*="name"]',
                ]
                for sel in author_selectors:
                    try:
                        elem = page.locator(sel).first
                        if await elem.count() > 0:
                            author_name = await elem.text_content() or "未知用户"
                            author_name = author_name.strip()
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            
            # 获取视频封面（用于解决防盗链问题）
            thumbnail_base64 = None
            try:
                poster_img = await page.evaluate('''() => {
                    const videoPoster = document.querySelector('video[poster]');
                    if (videoPoster) return videoPoster.poster;
                    const coverImg = document.querySelector('[class*="poster"] img, [class*="cover"] img');
                    if (coverImg) return coverImg.src;
                    const metaImg = document.querySelector('meta[property="og:image"]');
                    if (metaImg) return metaImg.content;
                    return null;
                }''')
                if poster_img:
                    thumbnail_data = await page.evaluate('async (url) => { try { const r = await fetch(url); const b = await r.blob(); return new Promise((res) => { const reader = new FileReader(); reader.onloadend = () => res(reader.result); reader.onerror = () => res(null); reader.readAsDataURL(b); }); } catch(e) { return null; } }', poster_img)
                    if thumbnail_data:
                        thumbnail_base64 = thumbnail_data
            except Exception as e:
                logger.debug(f'获取封面失败: {e}')
            
            # 如果找到图片，构建结果
            if final_images or desc:
                return {
                    'aweme_id': aweme_id,
                    'desc': desc,
                    'author': {
                        'uid': '',
                        'sec_uid': '',
                        'nickname': author_name,
                    },
                    'statistics': {
                        'digg_count': 0,
                        'comment_count': 0,
                        'play_count': 0,
                    },
                    'video': None,
                    'images': final_images,
                    'thumbnail_base64': thumbnail_base64,
                }
        except Exception as e:
            logger.debug(f"从页面元素提取失败: {e}")
        
        return None
    
    def _extract_aweme_from_data(self, data: Any, aweme_id: str) -> Optional[Dict[str, Any]]:
        """从解析的数据中提取 aweme 信息"""
        
        def find_aweme(obj, target_id):
            """递归查找包含目标 aweme_id 的对象"""
            if isinstance(obj, dict):
                # 检查是否是 aweme 对象
                aweme_id_val = obj.get('awemeId') or obj.get('aweme_id')
                if aweme_id_val == target_id:
                    return obj
                
                # 检查嵌套的 detail 对象
                detail = obj.get('detail', {})
                if isinstance(detail, dict):
                    detail_id = detail.get('awemeId')
                    if detail_id == target_id:
                        return detail
                
                # 检查 aweme 嵌套
                aweme = obj.get('aweme', {})
                if isinstance(aweme, dict):
                    found = find_aweme(aweme, target_id)
                    if found:
                        return found
                
                # 递归查找
                for v in obj.values():
                    result = find_aweme(v, target_id)
                    if result:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = find_aweme(item, target_id)
                    if result:
                        return result
            return None
        
        detail = find_aweme(data, aweme_id)
        if not detail:
            return None
        
        # 提取作者信息
        author_info = detail.get('authorInfo', {})
        if not author_info:
            author_info = detail.get('author', {})
        
        # 提取统计信息
        stats = detail.get('stats', {})
        if not stats:
            stats = detail.get('statistics', {})
        
        result = {
            'aweme_id': detail.get('awemeId') or detail.get('aweme_id') or aweme_id,
            'desc': detail.get('desc', ''),
            'author': {
                'uid': author_info.get('uid', ''),
                'sec_uid': author_info.get('secUid') or author_info.get('sec_uid', ''),
                'nickname': author_info.get('nickname', '未知用户'),
            },
            'statistics': {
                'digg_count': stats.get('diggCount') or stats.get('digg_count', 0),
                'comment_count': stats.get('commentCount') or stats.get('comment_count', 0),
                'play_count': stats.get('playCount') or stats.get('play_count', 0),
            },
            'video': None,
            'images': None,
        }
        
        # 提取图片
        images = detail.get('images', [])
        # 也检查 image_post_info
        if not images:
            image_post_info = detail.get('image_post_info', {})
            images = image_post_info.get('images', [])
        
        if images:
            result['images'] = []
            for img in images:
                if not isinstance(img, dict):
                    continue
                    
                # 尝试多个 URL 字段
                url_list = None
                for field in ['urlList', 'url_list', 'display_image', 'download_url']:
                    field_data = img.get(field)
                    if isinstance(field_data, dict):
                        url_list = field_data.get('urlList') or field_data.get('url_list', [])
                        break
                    elif isinstance(field_data, list) and field_data:
                        url_list = field_data
                        break
                
                # 构建图片信息
                img_info = {}
                if url_list:
                    img_info['url_list'] = url_list
                
                # 保留 base64 数据
                if img.get('base64'):
                    img_info['base64'] = img['base64']
                
                # 保留尺寸信息
                if img.get('width'):
                    img_info['width'] = img['width']
                if img.get('height'):
                    img_info['height'] = img['height']
                
                if img_info:
                    result['images'].append(img_info)
        
        return result
    
    async def download_video(self, url: str, quality: str = "best", format_id: Optional[str] = None, **kwargs) -> str:
        """下载抖音视频或图文作品"""
        if not DOUYIN_API_AVAILABLE:
            raise Exception("抖音 API 客户端未正确加载")
        
        import aiohttp
        
        async with DouyinAPIClient(cookies=self.cookies, proxy=self.proxy) as client:
            # 解析短链接
            real_url = await self._resolve_url(url, client)
            
            # 提取 aweme_id
            aweme_id = DouyinAPIClient.extract_aweme_id(real_url)
            if not aweme_id:
                raise Exception(f"无法从 URL 提取视频 ID: {real_url}")
            
            # 获取视频详情
            aweme_detail = await client.get_video_detail(aweme_id)
            if not aweme_detail:
                raise Exception(f"获取视频详情失败: aweme_id={aweme_id}")
            
            # 检测媒体类型
            media_type = client.detect_media_type(aweme_detail)
            
            # 生成文件名
            video_id = aweme_detail.get("aweme_id") or aweme_id
            title = self.sanitize_filename(aweme_detail.get("desc") or "douyin_video")
            
            if media_type == "video":
                # 下载视频
                if format_id:
                    video_info = client.build_bitrate_url(aweme_detail, format_id)
                else:
                    video_info = client.build_no_watermark_url(aweme_detail)
                
                if not video_info:
                    raise Exception("无法获取视频下载地址")
                
                video_url, headers = video_info
                filename = f"{title}_{video_id}.mp4"
                filepath = self.download_dir / filename
                
                logger.info(f"开始下载抖音视频: {filename}" + (f" (清晰度: {format_id})" if format_id else ""))
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(video_url, headers=headers, proxy=self.proxy) as response:
                        if response.status != 200:
                            raise Exception(f"下载失败: HTTP {response.status}")
                        
                        with open(filepath, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                
                logger.info(f"抖音视频下载完成: {filename}")
                return str(filepath)
            
            elif media_type == "gallery":
                # 下载图文作品
                return await self._download_gallery(aweme_detail, title, video_id)
            
            else:
                raise Exception(f"不支持的媒体类型: {media_type}")
    
    async def _download_gallery(self, aweme_detail: Dict, title: str, video_id: str) -> str:
        """下载图文作品"""
        import aiohttp
        import base64
        
        async with DouyinAPIClient(cookies=self.cookies, proxy=self.proxy) as client:
            image_urls = client.extract_image_urls(aweme_detail)
            if not image_urls:
                raise Exception("无法获取图文作品的图片")
            
            save_dir = self.download_dir / f"{title}_{video_id}"
            save_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"开始下载抖音图文作品: {len(image_urls)} 张图片")
            
            headers = {
                "Referer": "https://www.douyin.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            
            async with aiohttp.ClientSession() as session:
                for index, image_url in enumerate(image_urls, start=1):
                    # 判断是否为 base64 数据 URL
                    if image_url.startswith('data:'):
                        # 解析 base64 数据
                        try:
                            # 格式: data:image/png;base64,xxxxx
                            header, data = image_url.split(',', 1)
                            # 从 header 提取图片类型
                            if 'png' in header:
                                suffix = '.png'
                            elif 'webp' in header:
                                suffix = '.webp'
                            else:
                                suffix = '.jpg'
                            
                            img_data = base64.b64decode(data)
                            image_path = save_dir / f"{index:02d}{suffix}"
                            with open(image_path, 'wb') as f:
                                f.write(img_data)
                            logger.debug(f"已下载图片 {index}/{len(image_urls)} (base64)")
                        except Exception as e:
                            logger.warning(f"保存 base64 图片失败: {e}")
                        continue
                    
                    suffix = ".jpg"
                    if ".png" in image_url.lower():
                        suffix = ".png"
                    elif ".webp" in image_url.lower():
                        suffix = ".webp"
                    
                    image_path = save_dir / f"{index:02d}{suffix}"
                    
                    async with session.get(image_url, headers=headers, proxy=self.proxy) as response:
                        if response.status == 200:
                            with open(image_path, 'wb') as f:
                                async for chunk in response.content.iter_chunked(8192):
                                    f.write(chunk)
                            logger.debug(f"已下载图片 {index}/{len(image_urls)}")
            
            logger.info(f"抖音图文作品下载完成: {save_dir}")
            return str(save_dir)
    
    def _to_video_info(self, raw_info: Dict[str, Any], original_url: str, 
                       filesize_1080p: Optional[int] = None) -> VideoInfo:
        """将抖音 API 返回的数据转换为 VideoInfo"""
        video = raw_info.get("video") or {}
        author = raw_info.get("author", {})
        statistics = raw_info.get("statistics", {})
        aweme_id = str(raw_info.get("aweme_id") or "")
        
        # 检测媒体类型
        is_gallery = raw_info.get("image_post_info") or raw_info.get("images")
        
        # 提取封面（收集所有可能的封面 URL，优先使用 cover，失败时回退到 origin_cover）
        cover_urls = []  # 存储所有可用的封面 URL
        if video:
            # 首先添加 cover URL
            cover_data = video.get("cover")
            if isinstance(cover_data, dict):
                url_list = cover_data.get("url_list", [])
                cover_urls.extend(url_list)
            # 然后添加 origin_cover URL 作为备选
            origin_cover_data = video.get("origin_cover")
            if isinstance(origin_cover_data, dict):
                url_list = origin_cover_data.get("url_list", [])
                cover_urls.extend(url_list)
        
        cover = cover_urls[0] if cover_urls else None
        # 保存所有封面 URL，用于下载失败时的回退
        if cover_urls:
            raw_info['_all_cover_urls'] = cover_urls
        
        # 如果是图文，从第一张图片提取封面
        if not cover and is_gallery:
            images = raw_info.get("images") or raw_info.get("image_post_info", {}).get("images", [])
            if images:
                first_img = images[0]
                if isinstance(first_img, dict):
                    # 优先使用 base64
                    if first_img.get('base64'):
                        cover = first_img['base64']
                    else:
                        url_list = first_img.get("url_list") or first_img.get("urlList", [])
                        if url_list:
                            cover = url_list[0]
        
        # 检查是否有 thumbnail_base64
        if not cover and raw_info.get('thumbnail_base64'):
            cover = raw_info['thumbnail_base64']
        
        # 提取视频格式信息
        formats = []
        
        if is_gallery:
            # 图文作品
            images = raw_info.get("images") or raw_info.get("image_post_info", {}).get("images", [])
            image_count = len(images)
            
            for idx, img in enumerate(images):
                # 提取图片 URL
                img_url = None
                if isinstance(img, dict):
                    # API 格式
                    url_list = img.get("url_list", [])
                    if url_list:
                        img_url = url_list[0]
                    else:
                        # 网页解析格式
                        url_list = img.get("urlList", [])
                        if url_list:
                            img_url = url_list[0]
                    # 尝试其他字段
                    if not img_url:
                        for field in ["display_image", "owner_watermark_image", "download_url"]:
                            field_data = img.get(field, {})
                            if isinstance(field_data, dict):
                                urls = field_data.get("url_list") or field_data.get("urlList", [])
                                if urls:
                                    img_url = urls[0]
                                    break
                
                # 优先使用 base64 数据 URL
                final_url = img.get('base64') if isinstance(img, dict) and img.get('base64') else img_url
                
                # 提取分辨率
                width = img.get("width") if isinstance(img, dict) else None
                height = img.get("height") if isinstance(img, dict) else None
                resolution = f"{width}x{height}" if width and height else f"图片 {idx + 1}"
                
                formats.append(VideoFormat(
                    format_id=f"image_{idx}",
                    ext="jpg",
                    resolution=resolution,
                    filesize=None,
                    vcodec="none",
                    acodec="none",
                    quality=f"原图 {resolution}" if width and height else "原图",
                    is_audio_only=False,
                    is_video_only=False,
                    url=final_url,
                ))
        else:
            # 视频
            original_height = video.get("height", 0)
            original_width = video.get("width", 0)
            
            # 添加 1080p 选项
            if original_height >= 1080:
                formats.append(VideoFormat(
                    format_id="1080p",
                    ext="mp4",
                    resolution=f"{original_width}x{original_height}",
                    filesize=filesize_1080p,
                    vcodec="h264",
                    acodec="aac",
                    quality="1080p (超清)",
                    is_audio_only=False,
                    is_video_only=False,
                ))
            
            # 从 bit_rate 提取清晰度
            bit_rate_list = video.get("bit_rate", [])
            if bit_rate_list and isinstance(bit_rate_list, list):
                sorted_bit_rates = sorted(
                    bit_rate_list,
                    key=lambda x: x.get("play_addr", {}).get("height", 0) if isinstance(x.get("play_addr"), dict) else 0,
                    reverse=True
                )
                
                for idx, br_item in enumerate(sorted_bit_rates):
                    play_addr = br_item.get("play_addr", {})
                    if not isinstance(play_addr, dict):
                        continue
                    
                    url_list = play_addr.get("url_list", [])
                    if not url_list:
                        continue
                    
                    width = play_addr.get("width")
                    height = play_addr.get("height")
                    data_size = play_addr.get("data_size")
                    gear_name = br_item.get("gear_name", "")
                    
                    # 提取清晰度标签
                    quality_label = gear_name
                    video_extra = br_item.get("video_extra", "")
                    if video_extra:
                        try:
                            extra_data = json.loads(video_extra)
                            if extra_data.get("definition"):
                                quality_label = extra_data["definition"]
                        except:
                            pass
                    
                    formats.append(VideoFormat(
                        format_id=gear_name,
                        ext="mp4",
                        resolution=f"{width}x{height}" if width and height else None,
                        filesize=data_size,
                        vcodec="h264",
                        acodec="aac",
                        quality=quality_label,
                        is_audio_only=False,
                        is_video_only=False,
                    ))
        
        # 提取统计信息
        duration = video.get("duration", 0) if video else 0
        if duration:
            duration = duration // 1000
        
        return VideoInfo(
            id=aweme_id,
            title=raw_info.get("desc") or "未知标题",
            description=raw_info.get("desc"),
            thumbnail=cover,
            duration=duration,
            uploader=author.get("nickname") or "未知用户",
            uploader_id=str(author.get("uid") or author.get("sec_uid") or ""),
            view_count=self._safe_int(statistics.get("play_count")),
            like_count=self._safe_int(statistics.get("digg_count") or statistics.get("like_count")),
            comment_count=self._safe_int(statistics.get("comment_count")),
            platform=Platform.DOUYIN,
            original_url=original_url,
            formats=formats,
            best_format=formats[0] if formats else None,
        )
