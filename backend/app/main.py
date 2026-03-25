"""
Video Downloader API - FastAPI 应用入口
适配 FastAPI 0.115.x + Pydantic 2.7.x
"""
# 添加 deno 到 PATH（YouTube 签名挑战求解需要）- 必须在所有导入之前
import os
_deno_path = os.path.expanduser("~/.deno/bin")
if os.path.isdir(_deno_path) and _deno_path not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _deno_path + os.pathsep + os.environ.get("PATH", "")

import uuid
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger
import sys

from .core.config import settings
from .core.cache import cache
from .api import video_router


# ==================== 日志配置 ====================
def setup_logging():
    """配置日志输出"""
    logger.remove()
    
    # 控制台输出
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[request_id]}</cyan> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="DEBUG" if settings.DEBUG else "INFO",
        filter=lambda record: "request_id" in record["extra"],
    )
    
    # 无 request_id 的日志
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="DEBUG" if settings.DEBUG else "INFO",
        filter=lambda record: "request_id" not in record["extra"],
    )
    
    # 文件输出（保留7天，每天轮转）
    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        level="INFO",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[request_id]} | {name}:{function}:{line} - {message}",
        filter=lambda record: "request_id" in record["extra"],
    )
    
    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        level="INFO",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        filter=lambda record: "request_id" not in record["extra"],
    )


setup_logging()


# ==================== 请求 ID 中间件 ====================
class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求生成唯一 ID，便于日志追踪"""
    
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        
        # 在日志上下文中注入 request_id
        with logger.contextualize(request_id=request_id):
            logger.debug(f"请求开始: {request.method} {request.url.path}")
            response = await call_next(request)
            logger.debug(f"请求结束: {response.status_code}")
        
        response.headers["X-Request-ID"] = request_id
        return response


# ==================== 敏感信息脱敏工具 ====================
def sanitize_url(url: str) -> str:
    """URL 脱敏处理，隐藏敏感参数"""
    from urllib.parse import urlparse, parse_qs, urlencode
    
    if not url:
        return url
    
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        sensitive_keys = ['token', 'key', 'secret', 'password', 'cookie', 'session', 'auth']
        
        for k in list(params.keys()):
            if any(s in k.lower() for s in sensitive_keys):
                params[k] = ['***']
        
        sanitized_query = urlencode(params, doseq=True)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{sanitized_query}"[:200]
    except Exception:
        return url[:200]


# ==================== 应用生命周期 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    logger.info(f"📁 下载目录: {settings.DOWNLOAD_DIR}")
    logger.info(f"🔧 最大并发数: {settings.MAX_CONCURRENT_DOWNLOADS}")
    logger.info(f"⏱️ HTTP 超时: {settings.HTTP_TIMEOUT}秒")
    
    # 初始化缓存
    await cache.init()
    if settings.REDIS_ENABLED:
        logger.info(f"💾 Redis 缓存: {settings.REDIS_URL}")
    else:
        logger.info("💾 使用内存缓存")
    
    yield
    
    # 关闭时执行
    logger.info("👋 应用正在关闭...")
    
    # 关闭线程池
    from .services.downloader import downloader
    if hasattr(downloader, '_executor') and downloader._executor:
        downloader._executor.shutdown(wait=False)
        logger.info("✅ 线程池已关闭")


# ==================== 创建 FastAPI 应用 ====================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 全平台视频下载 API

支持 YouTube、B站、抖音、TikTok、Twitter、Instagram 等主流平台的视频解析与下载。

### 核心功能
- 🔍 视频信息解析（标题、封面、时长、格式等）
- ⬇️ 高速视频下载
- 🛡️ 防盗链突破（Referer/UA 伪装）
- 🎵 音频单独提取
- 📊 下载进度追踪

### 支持平台
- YouTube / YouTube Music
- Bilibili (B站)
- Douyin (抖音)
- TikTok
- Twitter / X
- Instagram
- 微博
- 以及更多 yt-dlp 支持的平台
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 添加请求 ID 中间件
app.add_middleware(RequestIDMiddleware)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)


# ==================== 全局异常处理器 ====================
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验异常处理"""
    errors = exc.errors()
    error_msgs = []
    for error in errors:
        loc = " -> ".join(str(x) for x in error.get("loc", []))
        msg = error.get("msg", "未知错误")
        error_msgs.append(f"{loc}: {msg}")
    
    logger.warning(f"参数校验失败: {'; '.join(error_msgs)}")
    
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "参数校验失败",
            "errors": errors,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常处理"""
    logger.warning(f"HTTP 异常: {exc.status_code} - {exc.detail}")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局未捕获异常处理"""
    error_msg = str(exc) or repr(exc) or "未知错误"
    error_trace = traceback.format_exc()
    
    logger.error(f"未捕获异常: {error_msg}\n{error_trace}")
    
    # 生产环境隐藏详细错误信息
    if settings.DEBUG:
        detail = error_msg
    else:
        detail = "服务内部错误，请稍后重试"
    
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": detail,
            "status_code": 500,
        },
    )


# 注册路由
app.include_router(video_router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )