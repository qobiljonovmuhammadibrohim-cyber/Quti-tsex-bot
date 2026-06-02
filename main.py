"""
main.py — v5: RedisStorage (fallback MemoryStorage)
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config.settings import BOT_TOKEN
from database.db import init_db
from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.state_reset_middleware import StateResetMiddleware
from bot.handlers import start, warehouse, worker, inspector, admin, reports_handler, orders, goals
from bot.handlers.search import router as search_router
from utils.scheduler import setup_scheduler
from web_panel import create_app, start_web
from bot.handlers.worker_adyol_pastel import router as ap_router
from bot.handlers.transfer import router as tr_router
from bot.handlers.qolip import router as qolip_router
from bot.handlers.attendance import router as att_router
from bot.handlers.worker_cabinet import router as cab_router
from bot.handlers.worker_topshiriq import router as task_router
from bot.handlers.worker_rulon import router as rulon_router
from bot.handlers.month_reset import router as reset_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

def _get_storage():
    return MemoryStorage()

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=_get_storage())
    dp.update.middleware(DbSessionMiddleware())
    dp.message.outer_middleware(StateResetMiddleware())
    dp.include_router(start.router)
    dp.include_router(task_router)
    dp.include_router(rulon_router)
    dp.include_router(warehouse.router)
    dp.include_router(worker.router)
    dp.include_router(inspector.router)
    dp.include_router(admin.router)
    dp.include_router(reports_handler.router)
    dp.include_router(search_router)
    dp.include_router(ap_router)
    dp.include_router(tr_router)
    dp.include_router(qolip_router)
    dp.include_router(att_router)
    dp.include_router(cab_router)
    dp.include_router(reset_router)
    dp.include_router(orders.router)
    dp.include_router(goals.router)
    await init_db()
    logger.info("DB tayyor!")
    sched = setup_scheduler(bot)
    sched.start()
    web_app    = create_app()
    web_runner = await start_web(web_app)
    from utils.cache import cache_cleanup_loop
    asyncio.create_task(cache_cleanup_loop())
    logger.info("Cache cleanup task ishga tushirildi")
    logger.info("Bot polling boshlandi...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sched.shutdown(wait=False)
        await web_runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
