"""
cache.py — In-memory cache tizimi
Tez-tez so'raladigan ma'lumotlarni xotirada saqlash.
"""
import time
import logging
from typing import Any, Callable, Optional
import asyncio

logger = logging.getLogger(__name__)


class Cache:
    """Oddiy TTL cache."""
    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key in self._store:
                expires_at, value = self._store[key]
                if expires_at > time.time():
                    self.hits += 1
                    return value
                else:
                    del self._store[key]
            self.misses += 1
            return None

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        async with self._lock:
            self._store[key] = (time.time() + ttl, value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def cleanup_expired(self) -> int:
        """Eski qiymatlarni tozalash."""
        now = time.time()
        async with self._lock:
            expired = [k for k, (exp, _) in self._store.items() if exp <= now]
            for k in expired:
                del self._store[k]
            return len(expired)

    def stats(self) -> dict:
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "size": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%",
        }


# Global cache instance
cache = Cache()


def cached(ttl: int = 60, key_prefix: str = ""):
    """Decorator: funksiya natijasini cache qilish."""
    def decorator(fn: Callable):
        async def wrapper(*args, **kwargs):
            # Cache kalit: prefix + args (db ni o'tkazib)
            cache_args = [a for a in args if not hasattr(a, "execute")]
            key_args = ",".join(str(a) for a in cache_args)
            key_kwargs = ",".join(f"{k}={v}" for k, v in sorted(kwargs.items())
                                  if not hasattr(v, "execute"))
            key = f"{key_prefix}:{fn.__name__}:{key_args}:{key_kwargs}"

            # Cache da bormi?
            result = await cache.get(key)
            if result is not None:
                logger.debug("Cache hit: %s", key[:60])
                return result

            # Yo'q bo'lsa, ishga tushir va saqla
            result = await fn(*args, **kwargs)
            await cache.set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator


# Background cleanup task
async def cache_cleanup_loop():
    """Har 5 daqiqada eski qiymatlarni tozalash."""
    while True:
        try:
            await asyncio.sleep(300)
            n = await cache.cleanup_expired()
            if n > 0:
                logger.info("Cache cleanup: %d ta eski yozuv o'chirildi", n)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Cache cleanup xato: %s", e)
