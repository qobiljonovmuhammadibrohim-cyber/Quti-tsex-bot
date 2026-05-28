import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN     = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
SUPERADMIN_ID = int(os.getenv("SUPERADMIN_ID", "0"))
_raw_db_url   = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/quti_bot")
# Railway postgres:// → postgresql+asyncpg:// ga o'girish
DATABASE_URL  = (
    _raw_db_url
    .replace("postgres://", "postgresql+asyncpg://")
    .replace("postgresql://", "postgresql+asyncpg://")
)
WEB_HOST      = os.getenv("WEB_HOST", "0.0.0.0")
WEB_URL       = os.getenv("WEB_URL", "")  # Railway URL: https://xxx.railway.app
WEB_PORT      = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
SECRET_KEY    = os.getenv("SECRET_KEY", "your-secret-key-change-this")
WEB_PASSWORD  = os.getenv("WEB_PASSWORD", "admin123")
REDIS_URL     = os.getenv("REDIS_URL", "")

def _parse_ids(env_key):
    return [int(x.strip()) for x in os.getenv(env_key, "").split(",") if x.strip().isdigit()]

ADMIN_IDS      = _parse_ids("ADMIN_IDS")
OMBORCHI_IDS   = _parse_ids("OMBORCHI_IDS")
NAZORATCHI_IDS = _parse_ids("NAZORATCHI_IDS")

RULON_RED_THRESHOLD    = 2
RULON_YELLOW_THRESHOLD = 5
DAILY_REPORT_TIME  = "20:00"
WEEKLY_REPORT_DAY  = 6
MONTHLY_REPORT_DAY = 10
