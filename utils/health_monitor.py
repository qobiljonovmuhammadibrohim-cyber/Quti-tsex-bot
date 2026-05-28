"""
health_monitor.py — Tizim salomatligi monitoringi
"""
import os
import time
import logging
import asyncio
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, WorkEntry, WarehouseProduct

logger = logging.getLogger(__name__)

# Tizim ishga tushish vaqti
STARTUP_TIME = time.time()


async def get_system_stats(db: AsyncSession) -> dict:
    """Tizim ko'rsatkichlarini qaytaradi."""
    stats = {
        "timestamp":  datetime.now().isoformat(),
        "uptime_sec": int(time.time() - STARTUP_TIME),
    }

    # Database statistika
    try:
        t0 = time.time()
        r_users = await db.execute(select(func.count(User.id)))
        users_n = int(r_users.scalar() or 0)

        r_works = await db.execute(select(func.count(WorkEntry.id)))
        works_n = int(r_works.scalar() or 0)

        r_prods = await db.execute(select(func.count(WarehouseProduct.id)))
        prods_n = int(r_prods.scalar() or 0)

        db_response_ms = int((time.time() - t0) * 1000)

        stats["database"] = {
            "users":       users_n,
            "work_entries": works_n,
            "products":     prods_n,
            "response_ms":  db_response_ms,
            "status":       "ok" if db_response_ms < 1000 else "slow",
        }
    except Exception as e:
        logger.error("DB health: %s", e)
        stats["database"] = {"status": "error", "error": str(e)[:100]}

    # Cache statistika
    try:
        from utils.cache import cache
        stats["cache"] = cache.stats()
    except Exception:
        stats["cache"] = {}

    # System resources
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        stats["system"] = {
            "memory_mb":  int(usage.ru_maxrss / 1024),  # kB → MB on Linux
            "cpu_time":   f"{usage.ru_utime + usage.ru_stime:.1f}s",
        }
    except Exception:
        stats["system"] = {}

    return stats


def format_uptime(seconds: int) -> str:
    """Uptime ni o'qiluvchi formatga aylantirish."""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    mins = (seconds % 3600) // 60
    if days > 0:
        return f"{days}k {hours}s {mins}d"
    elif hours > 0:
        return f"{hours}s {mins}d"
    else:
        return f"{mins}d {seconds % 60}s"
