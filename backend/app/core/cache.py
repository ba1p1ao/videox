"""
Redis 缓存模块
用于缓存视频解析结果，减少重复请求
"""
import json
import hashlib
from typing import Optional, Any
from loguru import logger

from .config import settings

# 尝试导入 Redis
try:
    import redis.asyncio as redis
    from redis.asyncio import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None
    Redis = None


class CacheBackend:
    """缓存后端抽象类"""
    
    async def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError
    
    async def set(self, key: str, value: Any, expire: int = None) -> bool:
        raise NotImplementedError
    
    async def delete(self, key: str) -> bool:
        raise NotImplementedError
    
    async def exists(self, key: str) -> bool:
        raise NotImplementedError
    
    async def ping(self) -> bool:
        """检查连接是否正常"""
        raise NotImplementedError
    
    async def close(self):
        """关闭连接"""
        pass


class RedisCache(CacheBackend):
    """Redis 缓存实现"""
    
    def __init__(self, url: str, max_connections: int = 50):
        self._url = url
        self._max_connections = max_connections
        self._client: Optional[redis.Redis] = None
    
    async def _get_client(self):
        """获取 Redis 客户端（带连接池）"""
        if self._client is None:
            self._client = redis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=self._max_connections,
                socket_keepalive=True,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
        return self._client
    
    async def get(self, key: str) -> Optional[Any]:
        try:
            client = await self._get_client()
            value = await client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning(f"Redis get 失败: {e}")
            return None
    
    async def set(self, key: str, value: Any, expire: int = None) -> bool:
        try:
            client = await self._get_client()
            serialized = json.dumps(value, ensure_ascii=False, default=str)
            if expire:
                await client.setex(key, expire, serialized)
            else:
                await client.set(key, serialized)
            return True
        except Exception as e:
            logger.warning(f"Redis set 失败: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        try:
            client = await self._get_client()
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Redis delete 失败: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        try:
            client = await self._get_client()
            return await client.exists(key) > 0
        except Exception as e:
            logger.warning(f"Redis exists 失败: {e}")
            return False
    
    async def ping(self) -> bool:
        """检查 Redis 连接"""
        try:
            client = await self._get_client()
            return await client.ping()
        except Exception:
            return False
    
    async def close(self):
        """关闭 Redis 连接"""
        if self._client:
            await self._client.close()
            self._client = None


class MemoryCache(CacheBackend):
    """内存缓存实现（无 Redis 时的降级方案）"""
    
    def __init__(self):
        self._store: dict = {}
        self._expires: dict = {}
    
    def _is_expired(self, key: str) -> bool:
        import time
        if key in self._expires:
            return time.time() > self._expires[key]
        return False
    
    async def get(self, key: str) -> Optional[Any]:
        if self._is_expired(key):
            self._store.pop(key, None)
            self._expires.pop(key, None)
            return None
        return self._store.get(key)
    
    async def set(self, key: str, value: Any, expire: int = None) -> bool:
        import time
        self._store[key] = value
        if expire:
            self._expires[key] = time.time() + expire
        return True
    
    async def delete(self, key: str) -> bool:
        self._store.pop(key, None)
        self._expires.pop(key, None)
        return True
    
    async def exists(self, key: str) -> bool:
        if self._is_expired(key):
            return False
        return key in self._store
    
    async def ping(self) -> bool:
        """内存缓存始终可用"""
        return True


class VideoCache:
    """视频解析结果缓存"""
    
    def __init__(self):
        self._backend: Optional[CacheBackend] = None
        self._initialized = False
        self._is_redis: bool = False
    
    async def init(self):
        """初始化缓存后端"""
        if self._initialized:
            return
        
        if settings.REDIS_ENABLED and REDIS_AVAILABLE:
            try:
                self._backend = RedisCache(
                    settings.REDIS_URL,
                    max_connections=settings.REDIS_MAX_CONNECTIONS
                )
                # 测试连接
                if await self._backend.ping():
                    logger.info(f"Redis 缓存已连接: {settings.REDIS_URL}")
                    self._is_redis = True
                else:
                    raise Exception("Redis ping 失败")
            except Exception as e:
                logger.warning(f"Redis 连接失败，使用内存缓存: {e}")
                self._backend = MemoryCache()
                self._is_redis = False
        else:
            logger.info("Redis 未启用，使用内存缓存")
            self._backend = MemoryCache()
            self._is_redis = False
        
        self._initialized = True
    
    @property
    def is_redis(self) -> bool:
        """是否使用 Redis"""
        return self._is_redis
    
    @staticmethod
    def _generate_cache_key(url: str) -> str:
        """生成缓存 key"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return f"video:parse:{url_hash}"
    
    async def get_parse_result(self, url: str) -> Optional[dict]:
        """获取解析结果缓存"""
        if not self._initialized:
            await self.init()
        
        key = self._generate_cache_key(url)
        result = await self._backend.get(key)
        
        if result:
            logger.debug(f"缓存命中: {url[:50]}...")
        
        return result
    
    async def set_parse_result(self, url: str, result: dict) -> bool:
        """设置解析结果缓存"""
        if not self._initialized:
            await self.init()
        
        key = self._generate_cache_key(url)
        return await self._backend.set(
            key, 
            result, 
            expire=settings.CACHE_EXPIRE_SECONDS
        )
    
    async def invalidate(self, url: str) -> bool:
        """清除缓存"""
        if not self._initialized:
            await self.init()
        
        key = self._generate_cache_key(url)
        return await self._backend.delete(key)
    
    async def health_check(self) -> dict:
        """健康检查"""
        if not self._initialized:
            await self.init()
        
        is_healthy = await self._backend.ping()
        
        return {
            "status": "ok" if is_healthy else "error",
            "type": "redis" if self._is_redis else "memory",
            "url": settings.REDIS_URL if self._is_redis else None,
        }
    
    async def close(self):
        """关闭缓存连接"""
        if self._backend:
            await self._backend.close()


# 全局缓存实例
cache = VideoCache()