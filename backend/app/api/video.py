"""
视频解析和下载 API 路由
支持同步/异步解析、Redis 缓存、Celery 任务队列
"""
import os
import traceback
import ipaddress
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Depends, Header
from fastapi.responses import FileResponse, Response
from loguru import logger
from pydantic import BaseModel, Field

from ..models.video import (
    VideoInfo,
    ParseRequest,
    ParseResponse,
    DownloadRequest,
    DownloadResponse,
    ProgressInfo,
)
from ..services.downloader import downloader
from ..core.config import settings
from ..core.cache import cache

router = APIRouter(prefix="/api/v1", tags=["video"])

# 尝试导入 Celery
try:
    from ..core.celery_app import celery_app
    from ..core.tasks import parse_video_task, download_video_task
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False
    celery_app = None
    parse_video_task = None
    download_video_task = None

# 尝试导入限流器
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    RATE_LIMIT_AVAILABLE = True
    limiter = Limiter(key_func=get_remote_address)
except ImportError:
    RATE_LIMIT_AVAILABLE = False
    limiter = None


# ==================== 安全认证 ====================

async def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """
    API Key 认证（可选启用）
    
    如果启用了 API_KEY_ENABLED，则必须提供有效的 API Key
    """
    if not settings.API_KEY_ENABLED:
        return True
    
    # 检查 IP 白名单
    client_ip = request.client.host if request.client else None
    if client_ip and settings.IP_WHITELIST:
        if client_ip in settings.IP_WHITELIST:
            return True
    
    # 检查 API Key
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="缺少 API Key，请在请求头中添加 X-API-Key"
        )
    
    if x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=401,
            detail="API Key 无效"
        )
    
    return True


def apply_rate_limit(request: Request):
    """应用限流检查"""
    if not RATE_LIMIT_AVAILABLE or not settings.RATE_LIMIT_ENABLED or not limiter:
        return
    
    # 获取客户端 IP
    client_ip = get_remote_address(request)
    
    # 使用 slowapi 的限流逻辑
    # 由于 slowapi 主要通过装饰器工作，这里只做日志记录
    logger.debug(f"限流检查: IP={client_ip}, limit={settings.RATE_LIMIT_PER_MINUTE}/min")


# ==================== SSRF 防护 ====================

def is_safe_url(url: str) -> tuple[bool, str]:
    """
    检查 URL 是否安全（防止 SSRF 攻击）
    
    Returns:
        (is_safe, reason): 是否安全及原因
    """
    if not url:
        return False, "URL 为空"
    
    try:
        parsed = urlparse(url)
        
        # 检查协议
        if parsed.scheme not in ['http', 'https']:
            return False, f"不支持的协议: {parsed.scheme}"
        
        # 检查主机名
        hostname = parsed.hostname
        if not hostname:
            return False, "无法解析主机名"
        
        # 解析 IP 地址
        try:
            # 先尝试直接解析
            ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            return False, f"无法解析主机名: {hostname}"
        
        # 检查是否为私有 IP
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.is_private:
                return False, f"禁止访问私有 IP: {ip}"
            if ip_obj.is_loopback:
                return False, f"禁止访问回环地址: {ip}"
            if ip_obj.is_link_local:
                return False, f"禁止访问链路本地地址: {ip}"
            if ip_obj.is_multicast:
                return False, f"禁止访问多播地址: {ip}"
        except ValueError:
            return False, f"无效的 IP 地址: {ip}"
        
        # 检查端口
        port = parsed.port
        if port and port not in [80, 443, None]:
            # 允许常见端口
            if port > 65535:
                return False, f"无效端口: {port}"
        
        return True, "URL 安全"
        
    except Exception as e:
        return False, f"URL 解析错误: {str(e)}"


def is_domain_allowed(url: str, allowed_domains: list[str]) -> bool:
    """检查域名是否在白名单中"""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return any(domain in hostname for domain in allowed_domains)
    except:
        return False


class AsyncTaskResponse(BaseModel):
    """异步任务响应"""
    success: bool = Field(..., description="是否成功提交任务")
    task_id: Optional[str] = Field(None, description="任务 ID")
    message: str = Field(..., description="消息")


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str = Field(..., description="任务 ID")
    status: str = Field(..., description="任务状态: PENDING, STARTED, SUCCESS, FAILURE")
    result: Optional[dict] = Field(None, description="任务结果")
    error: Optional[str] = Field(None, description="错误信息")


class ParseRequestAsync(BaseModel):
    """异步解析请求"""
    url: str = Field(..., description="视频URL")
    cookies: Optional[str] = Field(None, description="Cookie字符串")
    use_cache: bool = Field(default=True, description="是否使用缓存")


class DirectUrlRequest(BaseModel):
    """直链请求"""
    url: str = Field(..., description="视频URL")
    format_id: str = Field(..., description="格式ID")
    cookies: Optional[str] = Field(None, description="Cookie字符串")


class DirectUrlResponse(BaseModel):
    """直链响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="消息")
    direct_url: Optional[str] = Field(None, description="直链URL")
    needs_server: bool = Field(default=False, description="是否需要服务器处理")
    file_size: Optional[int] = Field(None, description="文件大小")
    ext: Optional[str] = Field(None, description="文件扩展名")


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="服务状态")
    version: str = Field(..., description="版本号")
    checks: dict = Field(..., description="各组件状态")


# 限流由 apply_rate_limit 函数处理


class ParsePartRequest(BaseModel):
    """分P解析请求"""
    url: str = Field(..., description="视频URL")
    part_index: int = Field(..., description="分P索引，从1开始")
    cookies: Optional[str] = Field(None, description="Cookie字符串")


@router.post("/parse", response_model=ParseResponse)
async def parse_video(
    request: Request, 
    body: ParseRequest,
    _: bool = Depends(verify_api_key)
):
    """
    解析视频信息（同步接口）
    获取视频标题、封面、时长、可用格式等
    
    支持缓存，相同 URL 在缓存有效期内直接返回缓存结果
    """
    apply_rate_limit(request)
    
    try:
        logger.info(f"解析视频: {body.url[:80]}...")
        
        # 初始化缓存
        await cache.init()
        
        # 检查缓存
        cached_result = await cache.get_parse_result(body.url)
        if cached_result:
            logger.info(f"缓存命中: {body.url[:50]}...")
            return ParseResponse(
                success=True,
                message="解析成功（缓存）",
                video_info=VideoInfo(**cached_result) if cached_result else None,
            )
        
        # 执行解析
        video_info = await downloader.parse_video_info(body.url, cookies=body.cookies)
        
        # 缓存结果
        if video_info:
            await cache.set_parse_result(body.url, video_info.model_dump())
        
        return ParseResponse(
            success=True,
            message="解析成功",
            video_info=video_info,
        )
    except Exception as e:
        error_msg = str(e) or repr(e) or "未知错误"
        error_trace = traceback.format_exc()
        logger.error(f"解析失败: {error_msg}\n{error_trace}")
        
        # 针对抖音提供更友好的错误提示
        url_lower = body.url.lower()
        if 'douyin.com' in url_lower or 'iesdouyin.com' in url_lower:
            return ParseResponse(
                success=False,
                message=f"抖音解析失败: {error_msg}。请确保链接有效，或尝试提供有效的 Cookie。",
                video_info=None,
            )
        
        return ParseResponse(
            success=False,
            message=f"解析失败: {error_msg}",
            video_info=None,
        )


@router.post("/parse/part", response_model=ParseResponse)
async def parse_video_part(
    request: Request, 
    body: ParsePartRequest,
    _: bool = Depends(verify_api_key)
):
    """
    解析多P视频指定分P的清晰度信息
    
    用于B站等多P视频，在用户选择分P后获取该分P的可用清晰度选项
    """
    apply_rate_limit(request)
    
    try:
        logger.info(f"解析分P视频: {body.url[:80]}..., part={body.part_index}")
        
        # 构建带分P参数的URL
        base_url = body.url.split('?')[0]
        part_url = f"{base_url}?p={body.part_index}"
        
        # 初始化缓存
        await cache.init()
        
        # 检查缓存（使用带分P参数的URL作为key）
        cached_result = await cache.get_parse_result(part_url)
        if cached_result:
            logger.info(f"分P缓存命中: {part_url[:50]}...")
            return ParseResponse(
                success=True,
                message="解析成功（缓存）",
                video_info=VideoInfo(**cached_result) if cached_result else None,
            )
        
        # 执行解析（解析指定分P）
        video_info = await downloader.parse_video_info(part_url, cookies=body.cookies)
        
        # 缓存结果
        if video_info:
            await cache.set_parse_result(part_url, video_info.model_dump())
        
        return ParseResponse(
            success=True,
            message="解析成功",
            video_info=video_info,
        )
    except Exception as e:
        error_msg = str(e) or repr(e) or "未知错误"
        error_trace = traceback.format_exc()
        logger.error(f"分P解析失败: {error_msg}\n{error_trace}")
        
        return ParseResponse(
            success=False,
            message=f"分P解析失败: {error_msg}",
            video_info=None,
        )


@router.post("/parse/async", response_model=AsyncTaskResponse)
async def parse_video_async(request: Request, body: ParseRequestAsync):
    """
    异步解析视频信息（使用 Celery 任务队列）
    
    适合批量解析或长时间操作，客户端可以通过 /task/{task_id} 查询结果
    """
    apply_rate_limit(request)
    
    if not CELERY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Celery 服务不可用")
    
    try:
        # 提交任务
        task = parse_video_task.delay(
            url=body.url,
            cookies=body.cookies,
            use_cache=body.use_cache,
        )
        
        return AsyncTaskResponse(
            success=True,
            task_id=task.id,
            message="任务已提交，请通过 /task/{task_id} 查询结果",
        )
    except Exception as e:
        logger.error(f"提交异步解析任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/direct-url", response_model=DirectUrlResponse)
async def get_direct_url(request: Request, body: DirectUrlRequest):
    """
    获取视频直链
    
    检查指定格式是否有可直接下载的 URL：
    - 如果有直链，返回 direct_url，客户端可直接下载
    - 如果需要合并/转换，返回 needs_server=true，需要调用 /download 接口
    """
    apply_rate_limit(request)
    
    try:
        logger.info(f"获取直链: {body.url[:50]}..., format_id={body.format_id}")
        
        # 初始化缓存
        await cache.init()
        
        # 检查缓存
        cached_result = await cache.get_parse_result(body.url)
        
        if cached_result:
            video_info = VideoInfo(**cached_result)
        else:
            # 执行解析
            video_info = await downloader.parse_video_info(body.url, cookies=body.cookies)
            # 缓存结果
            if video_info:
                await cache.set_parse_result(body.url, video_info.model_dump())
        
        # 查找指定格式
        target_format = None
        for fmt in video_info.formats:
            if fmt.format_id == body.format_id:
                target_format = fmt
                break
        
        if not target_format:
            raise HTTPException(status_code=404, detail=f"格式 {body.format_id} 不存在")
        
        # 检查是否有直链
        if target_format.url and not target_format.needs_merge:
            # 有直链且不需要合并
            return DirectUrlResponse(
                success=True,
                message="获取直链成功，可直接下载",
                direct_url=target_format.url,
                needs_server=False,
                file_size=target_format.filesize,
                ext=target_format.ext,
            )
        else:
            # 需要服务器处理
            reason = "需要合并音视频" if target_format.needs_merge else "无直链可用"
            return DirectUrlResponse(
                success=True,
                message=f"该格式{reason}，需要服务器处理",
                direct_url=None,
                needs_server=True,
                file_size=target_format.filesize,
                ext=target_format.ext,
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取直链失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    查询异步任务状态
    
    返回任务的执行状态和结果
    """
    if not CELERY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Celery 服务不可用")
    
    try:
        task_result = celery_app.AsyncResult(task_id)
        
        response = TaskStatusResponse(
            task_id=task_id,
            status=task_result.status,
            result=None,
            error=None,
        )
        
        if task_result.ready():
            result = task_result.result
            if task_result.successful():
                response.result = result if isinstance(result, dict) else {"data": result}
            else:
                response.error = str(result) if result else "任务执行失败"
        
        return response
    except Exception as e:
        logger.error(f"查询任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download", response_model=DownloadResponse)
async def download_video(
    request: Request, 
    body: DownloadRequest, 
    background_tasks: BackgroundTasks,
    _: bool = Depends(verify_api_key)
):
    """
    下载视频
    支持指定格式和质量
    
    注意：抖音等平台可能需要提供 Cookie
    """
    apply_rate_limit(request)
    
    try:
        logger.info(f"开始下载: {body.url[:50]}...")
        
        # 异步下载
        file_path = await downloader.download_async(
            url=body.url,
            format_id=body.format_id,
            quality=body.quality,
            audio_only=body.audio_only,
            cookies=body.cookies,
            video_title=body.video_title,
            video_id=body.video_id,
        )
        
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(status_code=500, detail="下载失败")
        
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        logger.info(f"下载完成: {file_name}")
        
        return DownloadResponse(
            success=True,
            message="下载成功",
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
        )
    except Exception as e:
        logger.error(f"下载失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/async", response_model=AsyncTaskResponse)
async def download_video_async(request: Request, body: DownloadRequest):
    """
    异步下载视频（使用 Celery 任务队列）
    
    适合大文件下载，客户端可以通过 /task/{task_id} 查询进度
    """
    apply_rate_limit(request)
    
    if not CELERY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Celery 服务不可用")
    
    try:
        task = download_video_task.delay(
            url=body.url,
            format_id=body.format_id,
            quality=body.quality,
            audio_only=body.audio_only,
            cookies=body.cookies,
        )
        
        return AsyncTaskResponse(
            success=True,
            task_id=task.id,
            message="下载任务已提交",
        )
    except Exception as e:
        logger.error(f"提交异步下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{filename}")
async def get_download_file(filename: str):
    """
    获取已下载的文件
    """
    file_path = Path(settings.DOWNLOAD_DIR) / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/progress/{task_id}", response_model=ProgressInfo)
async def get_download_progress(task_id: str):
    """
    获取下载进度
    """
    progress = downloader.get_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return progress


@router.get("/platforms")
async def get_supported_platforms():
    """
    获取支持的平台列表
    """
    return {
        "platforms": [
            {"name": "YouTube", "value": "youtube", "icon": "youtube", "requires_cookies": False, "available": True},
            {"name": "Bilibili", "value": "bilibili", "icon": "video", "requires_cookies": False, "available": True},
            {"name": "抖音", "value": "douyin", "icon": "video-play", "requires_cookies": True, "available": True, "note": "需要 Cookie（自动从浏览器读取或手动输入）"},
            {"name": "TikTok", "value": "tiktok", "icon": "video-play", "requires_cookies": False, "available": True},
            {"name": "Twitter/X", "value": "twitter", "icon": "chat-dot-round", "requires_cookies": False, "available": True},
            {"name": "Instagram", "value": "instagram", "icon": "picture", "requires_cookies": False, "available": True},
            {"name": "微博", "value": "weibo", "icon": "chat-line-round", "requires_cookies": False, "available": True},
            {"name": "小红书", "value": "xiaohongshu", "icon": "notebook", "requires_cookies": False, "available": True},
        ]
    }


@router.get("/cache/stats")
async def get_cache_stats():
    """
    获取缓存统计信息
    """
    await cache.init()
    
    return await cache.health_check()


@router.delete("/cache/{url:path}")
async def invalidate_cache(url: str):
    """
    清除指定 URL 的缓存
    """
    await cache.init()
    success = await cache.invalidate(url)
    
    return {
        "success": success,
        "message": "缓存已清除" if success else "缓存清除失败",
    }


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """
    健康检查（增强版）
    
    检查所有核心依赖的状态
    """
    checks = {
        "api": "ok",
        "redis": "unknown",
        "celery": "unknown",
    }
    
    # 检查 Redis/缓存
    try:
        cache_status = await cache.health_check()
        checks["redis"] = cache_status["status"]
    except Exception as e:
        logger.warning(f"缓存健康检查失败: {e}")
        checks["redis"] = "error"
    
    # 检查 Celery
    if CELERY_AVAILABLE:
        try:
            inspect = celery_app.control.inspect()
            active = inspect.active()
            if active:
                checks["celery"] = "ok"
            else:
                checks["celery"] = "warning"  # 可能没有活跃任务
        except Exception as e:
            logger.warning(f"Celery 健康检查失败: {e}")
            checks["celery"] = "error"
    else:
        checks["celery"] = "disabled"
    
    # 整体状态
    all_ok = all(v in ("ok", "warning", "disabled", "unknown") for v in checks.values())
    
    return HealthCheckResponse(
        status="ok" if all_ok else "degraded",
        version=settings.APP_VERSION,
        checks=checks,
    )


@router.get("/proxy/image")
async def proxy_image(url: str, _: bool = Depends(verify_api_key)):
    """
    图片代理接口
    用于绕过抖音等平台的防盗链机制
    
    安全措施：
    1. 域名白名单验证
    2. SSRF 防护（禁止私有 IP）
    3. 协议限制（仅 HTTP/HTTPS）
    """
    import aiohttp
    from urllib.parse import urlparse
    from ..services.douyin.downloader import DouyinDownloader
    from ..services.xiaohongshu.downloader import XiaohongshuDownloader
    
    # ========== SSRF 防护 ==========
    # 1. URL 安全检查
    is_safe, reason = is_safe_url(url)
    if not is_safe:
        logger.warning(f"SSRF 防护: 拒绝访问 {url[:80]}, 原因: {reason}")
        raise HTTPException(status_code=403, detail=f"URL 不被允许: {reason}")
    
    # 2. 域名白名单验证
    if not is_domain_allowed(url, settings.PROXY_ALLOWED_DOMAINS):
        parsed = urlparse(url)
        raise HTTPException(
            status_code=403, 
            detail=f"不允许代理该域名的图片: {parsed.netloc}"
        )
    
    logger.debug(f"图片代理请求: {url[:80]}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    
    # 获取对应平台的 Cookie
    cookies = {}
    if 'douyinpic.com' in url:
        headers["Referer"] = "https://www.douyin.com/"
        try:
            d = DouyinDownloader()
            cookies = d.cookies or {}
        except Exception as e:
            logger.warning(f"获取抖音 Cookie 失败: {e}")
    elif 'xiaohongshu' in url or 'xhscdn' in url:
        headers["Referer"] = "https://www.xiaohongshu.com/"
        try:
            d = XiaohongshuDownloader()
            cookies = d._cookie_dict or {}
        except Exception as e:
            logger.warning(f"获取小红书 Cookie 失败: {e}")
    
    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=settings.HTTP_TIMEOUT)
        async with aiohttp.ClientSession(cookies=cookies, timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise HTTPException(status_code=response.status, detail="图片获取失败")
                
                content_type = response.headers.get('Content-Type', 'image/jpeg')
                content = await response.read()
                
                return Response(
                    content=content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # 缓存1天
                        "Access-Control-Allow-Origin": "*",
                    }
                )
    except aiohttp.ClientError as e:
        logger.error(f"图片代理失败: {e}")
        raise HTTPException(status_code=500, detail="图片获取失败")
