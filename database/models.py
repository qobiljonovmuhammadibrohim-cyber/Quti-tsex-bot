"""
models.py — TUZATILGAN
TUZATISHLAR:
  1. WorkSession.duration_minutes: @property o'rniga Column(Integer)
     saqlanadi — queries.py da to'g'ridan yozish mumkin
  2. WorkSession.is_open: @property saqlanadi (faqat o'qish)
  3. WorkPrice.updated_at: set_price da to'g'ri ishlatilishi uchun
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    ForeignKey, Text, Enum, BigInteger, Date
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, declarative_base
from datetime import date, datetime
from sqlalchemy.sql import func
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    superadmin = "superadmin"
    admin      = "admin"
    omborchi   = "omborchi"
    nazoratchi = "nazoratchi"
    ishchi     = "ishchi"


class ProductCategory(str, enum.Enum):
    rulon            = "rulon"
    gofra            = "gofra"
    gofra_zagatovka  = "gofra_zagatovka"
    xromazes         = "xromazes"
    laminat_xromazes = "laminat_xromazes"
    yarim_tayyor     = "yarim_tayyor"
    qolip            = "qolip"
    tayyor_mahsulot  = "tayyor_mahsulot"
    adyol_zapchast   = "adyol_zapchast"
    uskuna_zapchast  = "uskuna_zapchast"


YARIM_TAYYOR_TURLAR = {
    "tiger_uchun":         "Tiger kesish uchun qog'ozlar",
    "stepler_uchun":       "Stepler tikish uchun kesilgan materiallar",
    "salafan_uchun":       "Rulonga salafan uchun materiallar",
    "yopish_uchun":        "Yopishtirish uchun kesilgan qog'ozlar",
    "adyol_tikish_uchun":  "Adyol tikish uchun kesilgan qog'ozlar",
    "pastel_tikish_uchun": "Pastel tikish uchun kesilgan qog'ozlar",
    "adyol_qoqish_uchun":  "Adyol qoqish uchun tikilgan mahsulotlar",
    "pastel_qoqish_uchun": "Pastel qoqish uchun tikilgan mahsulotlar",
    "xom_komple":          "Xom adyollar va pastellar (komple)",
    "kapalak":             "Kapalak adyollar va pastellar",
}


class WorkStatus(str, enum.Enum):
    pending        = "pending"
    approved       = "approved"
    adjusted       = "adjusted"
    rejected       = "rejected"
    edit_requested = "edit_requested"


class QualityGrade(str, enum.Enum):
    grade_1 = "1"
    grade_2 = "2"
    grade_3 = "3"


QUALITY_COEFFICIENTS = {
    QualityGrade.grade_1: 1.0,
    QualityGrade.grade_2: 0.8,
    QualityGrade.grade_3: 0.6,
}


class PenaltyType(str, enum.Enum):
    jarima   = "jarima"
    xaypsan1 = "xaypsan1"
    xaypsan2 = "xaypsan2"


class WorkType(str, enum.Enum):
    tiger_kesish    = "tiger_kesish"
    gofra_kiley     = "gofra_kiley"
    gofra_ishlab    = "gofra_ishlab"
    list_qogoz      = "list_qogoz"
    laminatsiya     = "laminatsiya"
    zagatovka       = "zagatovka"
    stepler_tikish  = "stepler_tikish"
    rulon_orash     = "rulon_orash"
    rulonga_salafan = "rulonga_salafan"
    yopishtirma     = "yopishtirma"
    adyol_tikish    = "adyol_tikish"
    diplomat_tikish = "diplomat_tikish"
    adyol_qoqish    = "adyol_qoqish"
    pastel_qoqish   = "pastel_qoqish"
    rulon_ishlab    = "rulon_ishlab"   # rulon ishlab chiqarish (zanjir boshi)



class ProductHolat(str, enum.Enum):
    yaroqli     = "yaroqli"
    tamir_talab = "tamir_talab"
    yaroqsiz    = "yaroqsiz"


QOLIP_TURLAR = {
    "fast_food":      "🍔 Fast food qolip",
    "tushli":         "🍱 Tushlik qolip",
    "shirinlik":      "🍰 Shirinlik qolip",
    "blok_4quloqli":  "📦 Blok 4 quloqli",
    "adyol_3qism":    "🛏 Adyol 3 qism",
    "pastel_3qism":   "💼 Pastel 3 qism",
    "boshqa":         "📝 Boshqa",
}

class SmenaType(str, enum.Enum):
    kunduzgi = "kunduzgi"
    kechki   = "kechki"


class User(Base):
    __tablename__ = "users"

    id          = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name   = Column(String(200), nullable=False)
    phone       = Column(String(20), nullable=True)
    role        = Column(Enum(UserRole), default=UserRole.ishchi, nullable=False)
    is_active   = Column(Boolean, default=True)
    web_token   = Column(String(80), nullable=True, unique=True)  # Web panel kirish tokeni
    created_at  = Column(DateTime, server_default=func.now())

    works           = relationship("WorkEntry",    back_populates="worker",        foreign_keys="[WorkEntry.worker_id]")
    inspected       = relationship("WorkEntry",    back_populates="inspector",     foreign_keys="[WorkEntry.inspector_id]")
    penalties       = relationship("Penalty",      back_populates="worker",        foreign_keys="[Penalty.worker_id]")
    given_penalties = relationship("Penalty",      back_populates="inspector",     foreign_keys="[Penalty.inspector_id]")
    advances        = relationship("Advance",      back_populates="worker",        foreign_keys="[Advance.worker_id]")
    given_advances  = relationship("Advance",      back_populates="admin",         foreign_keys="[Advance.admin_id]")
    salary_reports  = relationship("SalaryReport", back_populates="worker",        foreign_keys="[SalaryReport.worker_id]")
    warehouse_logs  = relationship("WarehouseLog", back_populates="user",          foreign_keys="[WarehouseLog.user_id]")
    work_sessions   = relationship("WorkSession",  back_populates="worker",        foreign_keys="[WorkSession.worker_id]")

class WorkSession(Base):
    __tablename__ = "work_sessions"

    id               = Column(Integer, primary_key=True)
    worker_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    smena            = Column(Enum(SmenaType), nullable=False, default=SmenaType.kunduzgi)
    opened_at        = Column(DateTime, nullable=False, server_default=func.now())
    closed_at        = Column(DateTime, nullable=True)
    work_date        = Column(Date, server_default=func.current_date())
    # TUZATILDI: duration_minutes Column sifatida — queries.py da to'g'ri yozish mumkin
    duration_minutes = Column(Integer, nullable=True, default=None)
    izoh             = Column(Text, nullable=True)

    worker = relationship("User", back_populates="work_sessions", foreign_keys=[worker_id])

    @property
    def is_open(self) -> bool:
        """Smena hali yopilmagan."""
        return self.closed_at is None

    def calc_duration(self) -> int:
        """Vaqt farqini daqiqada hisoblaydi (yopilgan sessiyalar uchun)."""
        if self.opened_at and self.closed_at:
            return int((self.closed_at - self.opened_at).total_seconds() / 60)
        return 0


class WarehouseProduct(Base):
    __tablename__ = "warehouse_products"

    id               = Column(Integer, primary_key=True)
    category         = Column(Enum(ProductCategory), nullable=False)
    name             = Column(String(300), nullable=False)
    razmer           = Column(String(100), nullable=True)
    rang             = Column(String(100), nullable=True)
    tur              = Column(String(100), nullable=True)
    qalinlik          = Column(Float, nullable=True)
    birlik            = Column(String(20), default="dona")
    miqdor            = Column(Float, default=0)
    min_threshold     = Column(Float, default=2)
    yellow_threshold  = Column(Float, default=5)
    is_active         = Column(Boolean, default=True)
    # Xromazeslar uchun: aniq razmer + o'lcham kategoriyasi
    # razmer       = "98×62.5"  ← sinxronizatsiya uchun (zagatovka↔gofra_kley)
    # razmer_tur   = "Katta"    ← tiger narxi uchun (Katta/O'rta/Kichik)
    razmer_tur        = Column(String(20), nullable=True)  # Katta/O'rta/Kichik
    qism              = Column(String(20), nullable=True)  # tepa/past/yon/paddo
    yonalish          = Column(String(20), nullable=True)  # tiger/zagatovka
    zero_notified     = Column(Boolean, default=False, nullable=True)  # 0 ga tushganda admin xabardor
    yonalish          = Column(String(20), nullable=True)  # tiger | zagatovka | laminat
    # Qoliplar uchun
    holat             = Column(Enum(ProductHolat), nullable=True)
    holat_izoh        = Column(Text, nullable=True)
    razmer_normalized = Column(String(200), nullable=True)
    created_at       = Column(DateTime, server_default=func.now())
    updated_at       = Column(DateTime, onupdate=func.now())

    logs = relationship("WarehouseLog", back_populates="product")


class WarehouseLog(Base):
    __tablename__ = "warehouse_logs"

    id            = Column(Integer, primary_key=True)
    product_id    = Column(Integer, ForeignKey("warehouse_products.id"), nullable=False)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=True)   # None bo'lsa log saqlanmaydi
    amal          = Column(String(20), nullable=False)
    miqdor        = Column(Float, nullable=False)
    oldin         = Column(Float, nullable=False)
    keyin         = Column(Float, nullable=False)
    izoh          = Column(Text, nullable=True)
    work_entry_id = Column(Integer, ForeignKey("work_entries.id"), nullable=True)
    created_at    = Column(DateTime, server_default=func.now())

    @hybrid_property
    def delta(self):
        """Miqdor o'zgarishi: keyin - oldin (kirim musbat, chiqim manfiy)."""
        return (self.keyin or 0) - (self.oldin or 0)

    product    = relationship("WarehouseProduct", back_populates="logs")
    user       = relationship("User",      back_populates="warehouse_logs", foreign_keys=[user_id])
    work_entry = relationship("WorkEntry", back_populates="warehouse_logs", foreign_keys=[work_entry_id])


class WorkEntry(Base):
    __tablename__ = "work_entries"

    id            = Column(Integer, primary_key=True)
    worker_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    inspector_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    work_type     = Column(Enum(WorkType), nullable=False)

    mahsulot_nomi = Column(String(300), nullable=True)
    razmer        = Column(String(100), nullable=True)
    rang          = Column(String(100), nullable=True)
    tur           = Column(String(100), nullable=True)
    sloy          = Column(String(10),  nullable=True)

    soni          = Column(Float, nullable=False, default=0)
    original_soni = Column(Float, nullable=True)
    birlik_narx   = Column(Float, nullable=True, default=0)
    jami_summa    = Column(Float, nullable=True, default=0)

    rulon_details = Column(Text, nullable=True)

    status        = Column(Enum(WorkStatus), default=WorkStatus.pending, nullable=False)
    rad_sababi    = Column(Text, nullable=True)
    tuzatish_izoh = Column(Text, nullable=True)

    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    quality_grade = Column(Enum(QualityGrade), nullable=True, default=QualityGrade.grade_1)
    qc_note       = Column(Text, nullable=True)

    worker_edit_requested = Column(Boolean, default=False)
    worker_edit_note      = Column(Text, nullable=True)

    work_date  = Column(Date, server_default=func.current_date())
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    worker    = relationship("User",     back_populates="works",     foreign_keys=[worker_id])
    inspector = relationship("User",     back_populates="inspected", foreign_keys=[inspector_id])
    penalties      = relationship("Penalty",      back_populates="work_entry")
    warehouse_logs = relationship("WarehouseLog", back_populates="work_entry",
                                  foreign_keys="[WarehouseLog.work_entry_id]")


class WorkPrice(Base):
    __tablename__ = "work_prices"

    id          = Column(Integer, primary_key=True)
    work_type   = Column(Enum(WorkType), nullable=False)
    razmer_turi = Column(String(100), nullable=True)
    narx        = Column(Float, nullable=False)
    birlik      = Column(String(50), default="dona")
    izoh        = Column(Text, nullable=True)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, server_default=func.now())
    updated_at  = Column(DateTime, onupdate=func.now())


class Penalty(Base):
    __tablename__ = "penalties"

    id               = Column(Integer, primary_key=True)
    worker_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    inspector_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    work_entry_id    = Column(Integer, ForeignKey("work_entries.id"), nullable=True)
    penalty_type     = Column(Enum(PenaltyType), nullable=False)
    summa            = Column(Float, default=0)
    sabab            = Column(Text, nullable=False)
    worker_confirmed = Column(Boolean, default=False)
    created_at       = Column(DateTime, server_default=func.now())

    worker     = relationship("User", back_populates="penalties",       foreign_keys=[worker_id])
    inspector  = relationship("User", back_populates="given_penalties", foreign_keys=[inspector_id])
    work_entry = relationship("WorkEntry", back_populates="penalties")


class Advance(Base):
    __tablename__ = "advances"

    id         = Column(Integer, primary_key=True)
    worker_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    admin_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    summa      = Column(Float, nullable=False)
    izoh       = Column(Text, nullable=True)
    oy         = Column(Integer, nullable=False)
    yil        = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    worker = relationship("User", back_populates="advances",       foreign_keys=[worker_id])
    admin  = relationship("User", back_populates="given_advances", foreign_keys=[admin_id])


class SalaryReport(Base):
    __tablename__ = "salary_reports"

    id               = Column(Integer, primary_key=True)
    worker_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    oy               = Column(Integer, nullable=False)
    yil              = Column(Integer, nullable=False)
    jami_ish_summa   = Column(Float, default=0)
    jami_jarima      = Column(Float, default=0)
    jami_avans       = Column(Float, default=0)
    sof_maosh        = Column(Float, default=0)
    admin_tasdiqladi = Column(Boolean, default=False)
    tasdiq_vaqti     = Column(DateTime, nullable=True)
    worker_notified  = Column(Boolean, default=False)
    created_at       = Column(DateTime, server_default=func.now())

    worker = relationship("User", back_populates="salary_reports", foreign_keys=[worker_id])


# ═══ DAVOMAT (KASALLIK / TA'TIL) ══════════════════════════════════════════════

class OrderStatus(str, enum.Enum):
    """Buyurtma holatlari."""
    yangi         = "yangi"
    qabul_qilindi = "qabul_qilindi"
    ishlab        = "ishlab"
    tayyor        = "tayyor"
    yetkazildi    = "yetkazildi"
    bekor         = "bekor"


class AttendanceType(str, enum.Enum):
    ish        = "ish"        # Oddiy ish kuni
    kasallik   = "kasallik"   # Kasallik varaqasi bilan
    tatil      = "tatil"      # Rasmiy ta'til
    sababli    = "sababli"    # Sababli (admin tasdiqlagan)
    sababsiz   = "sababsiz"   # Sababsiz (jarima yozilishi mumkin)


class Attendance(Base):
    __tablename__ = "attendance"

    id          = Column(Integer, primary_key=True)
    worker_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    sana        = Column(Date, nullable=False, default=date.today)
    tur         = Column(Enum(AttendanceType), nullable=False, default=AttendanceType.ish)
    izoh        = Column(Text, nullable=True)
    admin_id    = Column(Integer, ForeignKey("users.id"), nullable=True)  # tasdiqlagan
    tasdiq      = Column(Boolean, default=False)
    created_at  = Column(DateTime, server_default=func.now())

    worker = relationship("User", foreign_keys=[worker_id])
    admin  = relationship("User", foreign_keys=[admin_id])


# ═══ OYLIK RESET ══════════════════════════════════════════════════════════════

class MonthReset(Base):
    __tablename__ = "month_resets"

    id          = Column(Integer, primary_key=True)
    oy          = Column(Integer, nullable=False)
    yil         = Column(Integer, nullable=False)
    admin_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    holat       = Column(String(20), default="yakunlandi")  # yakunlandi | bekor
    izoh        = Column(Text, nullable=True)
    created_at  = Column(DateTime, server_default=func.now())

    admin = relationship("User", foreign_keys=[admin_id])


# ═══ TELEGRAM GURUH SOZLAMALARI ═══════════════════════════════════════════════

class GroupType(str, enum.Enum):
    inspector  = "inspector"   # Nazoratchilar guruhi
    admin      = "admin"       # Admin guruhi
    ishchi     = "ishchi"      # Ishchilar guruhi (umumiy)
    hisobot    = "hisobot"     # Hisobotlar guruhi


class TelegramGroup(Base):
    __tablename__ = "telegram_groups"

    id          = Column(Integer, primary_key=True)
    group_id    = Column(BigInteger, unique=True, nullable=False)
    group_name  = Column(String(200), nullable=True)
    group_type  = Column(Enum(GroupType), nullable=False)
    is_active   = Column(Boolean, default=True)
    added_by    = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime, server_default=func.now())

    added_by_user = relationship("User", foreign_keys=[added_by])


class Customer(Base):
    """Mijoz."""
    __tablename__ = "customers"

    id          = Column(Integer, primary_key=True)
    full_name   = Column(String(150), nullable=False)
    phone       = Column(String(30),  nullable=True)
    address     = Column(Text,         nullable=True)
    company     = Column(String(150), nullable=True)
    notes       = Column(Text,         nullable=True)

    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    """Buyurtma."""
    __tablename__ = "orders"

    id              = Column(Integer, primary_key=True)
    order_number    = Column(String(30), unique=True, nullable=False)  # ORD-2026-0001
    customer_id     = Column(Integer, ForeignKey("customers.id"), nullable=False)

    title           = Column(String(200), nullable=False)
    description     = Column(Text, nullable=True)

    status          = Column(Enum(OrderStatus), default=OrderStatus.yangi)
    priority        = Column(Integer, default=3)  # 1-5, 1 eng yuqori

    total_amount    = Column(Float, default=0.0)
    paid_amount     = Column(Float, default=0.0)

    deadline        = Column(Date,     nullable=True)
    created_by      = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    completed_at    = Column(DateTime, nullable=True)


class OrderItem(Base):
    """Buyurtma elementi (mahsulot pozitsiyasi)."""
    __tablename__ = "order_items"

    id              = Column(Integer, primary_key=True)
    order_id        = Column(Integer, ForeignKey("orders.id"), nullable=False)

    product_name    = Column(String(200), nullable=False)
    razmer          = Column(String(50),  nullable=True)
    rang            = Column(String(50),  nullable=True)

    quantity        = Column(Float, nullable=False)
    unit            = Column(String(20), default="dona")
    price_per_unit  = Column(Float, default=0.0)
    subtotal        = Column(Float, default=0.0)

    produced_qty    = Column(Float, default=0.0)  # nechta ishlab chiqarildi
    notes           = Column(Text, nullable=True)


class Goal(Base):
    """Ishchi maqsadi (kunlik/oylik)."""
    __tablename__ = "goals"

    id          = Column(Integer, primary_key=True)
    worker_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    period_type = Column(String(20), nullable=False)  # "daily" | "monthly"
    period_date = Column(Date, nullable=False)        # oy uchun 1-kun saqlanadi
    target_amount = Column(Float, nullable=False)
    target_count  = Column(Integer, default=0)
    set_by      = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active   = Column(Boolean, default=True)
    notes       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class TopshiriqStatus(str, enum.Enum):
    """Topshiriq holati."""
    tayinlangan = "tayinlangan"   # admin berdi, ishchi hali boshlamagan
    qisman      = "qisman"        # ishchi qisman bajardi, admin qarori kutilmoqda
    bajarilgan  = "bajarilgan"    # to'liq bajarildi
    yakunlangan = "yakunlangan"   # admin yopdi
    bekor       = "bekor"         # bekor qilindi


class Topshiriq(Base):
    """Admin tomonidan ishchiga berilgan topshiriq (vazifa)."""
    __tablename__ = "topshiriqlar"

    id            = Column(Integer, primary_key=True)
    worker_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    admin_id      = Column(Integer, ForeignKey("users.id"), nullable=True)
    work_type     = Column(
        Enum(WorkType, native_enum=False, length=50,
             values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    razmer_turi   = Column(String(100), nullable=True)   # Katta/O'rta/Kichik yoki variant
    target_soni   = Column(Float, nullable=False, default=0)   # reja miqdori
    done_soni     = Column(Float, nullable=False, default=0)   # bajarilgan miqdor
    product_id    = Column(Integer, ForeignKey("warehouse_products.id"), nullable=True)  # bog'langan material
    deadline      = Column(Date, nullable=True)
    status        = Column(
        Enum(TopshiriqStatus, native_enum=False, length=20,
             values_callable=lambda obj: [e.value for e in obj]),
        default=TopshiriqStatus.tayinlangan, nullable=False,
    )
    izoh          = Column(Text, nullable=True)
    work_entry_id = Column(Integer, ForeignKey("work_entries.id"), nullable=True)  # bajarilganda yaratilgan ish
    created_at    = Column(DateTime, server_default=func.now())
    updated_at    = Column(DateTime, onupdate=func.now())
    completed_at  = Column(DateTime, nullable=True)

