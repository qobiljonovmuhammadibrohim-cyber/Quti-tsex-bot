"""
web_panel_ombor.py — OMBORCHI uchun alohida, mustaqil Web panel.
Faqat ombor bilan bog'liq funksiyalar. Admin sahifalariga havola yo'q.
Mobil-birinchi dizayn, pastki navigatsiya paneli bilan.
"""
from datetime import date, datetime
from aiohttp import web
from sqlalchemy import select, func
import sqlalchemy.sql.functions as sf
from sqlalchemy import case as sa_case

from database.db import AsyncSessionLocal
from database.models import WarehouseProduct, WarehouseLog, ProductCategory
from database.queries import update_product_miqdor

# Umumiy yordamchilar (web_panel.py dan)
from web_panel import _current, _require_role, h, _CAT_CFG


# ─── Kategoriya nomlari ──────────────────────────────────────────────────
CAT_LABELS = {
    "rulon": "🌀 Rulonlar",
    "gofra": "📋 Go'fralar",
    "gofra_zagatovka": "✂️ Zagatovka",
    "xromazes": "🖨 Xromazes",
    "laminat_xromazes": "✨ Laminat",
    "yarim_tayyor": "🧩 Yarim tayyor",
    "qolip": "🔲 Qoliplar",
    "tayyor_mahsulot": "📦 Tayyor mahsulot",
    "adyol_zapchast": "🧵 Adyol zapchast",
    "uskuna_zapchast": "🔧 Uskuna zapchast",
}


# ─── Asosiy shablon (mustaqil) ───────────────────────────────────────────
def _base_ombor(title: str, active: str, content: str, name: str = "Omborchi") -> str:
    """Omborchi paneli uchun mustaqil HTML shablon — pastki navigatsiya bilan."""
    nav = [
        ("home", "🏠", "Bosh", "/web/ombor-panel"),
        ("ops", "➕", "Kirim/Chiqim", "/web/ombor-panel/operatsiya"),
        ("cats", "📦", "Bo'limlar", "/web/ombor-panel/bolimlar"),
        ("report", "📊", "Hisobot", "/web/ombor-panel/hisobot"),
        ("history", "📋", "Tarix", "/web/ombor-panel/tarix"),
    ]
    nav_html = ""
    for key, icon, label, url in nav:
        cls = "nav-active" if key == active else ""
        nav_html += (
            '<a href="' + url + '" class="bnav-item ' + cls + '">'
            '<span class="bnav-icon">' + icon + '</span>'
            '<span class="bnav-label">' + label + '</span></a>'
        )

    return (
        '<!DOCTYPE html><html lang="uz"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">'
        '<title>' + h(title) + ' — Ombor</title>'
        + _OMBOR_CSS +
        '</head><body>'
        '<header class="top-bar">'
        '<div class="tb-left"><span class="tb-logo">📦</span><div>'
        '<div class="tb-title">Ombor paneli</div>'
        '<div class="tb-sub">' + h(name) + '</div></div></div>'
        '<a href="/web/logout" class="tb-logout">Chiqish</a>'
        '</header>'
        '<main class="content">' + content + '</main>'
        '<nav class="bottom-nav">' + nav_html + '</nav>'
        '</body></html>'
    )


# ─── 1. BOSH SAHIFA ──────────────────────────────────────────────────────
@_require_role("omborchi")
async def ombor_home(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    today = date.today()

    async with AsyncSessionLocal() as db:
        total = int((await db.execute(
            select(func.count(WarehouseProduct.id)).where(WarehouseProduct.is_active == True)
        )).scalar() or 0)
        low_n = int((await db.execute(
            select(func.count(WarehouseProduct.id)).where(
                WarehouseProduct.is_active == True,
                WarehouseProduct.miqdor <= WarehouseProduct.min_threshold,
                WarehouseProduct.miqdor > 0,
            )
        )).scalar() or 0)
        zero_n = int((await db.execute(
            select(func.count(WarehouseProduct.id)).where(
                WarehouseProduct.is_active == True, WarehouseProduct.miqdor <= 0
            )
        )).scalar() or 0)
        today_ops = int((await db.execute(
            select(func.count(WarehouseLog.id)).where(func.date(WarehouseLog.created_at) == today)
        )).scalar() or 0)

        low_list = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True,
                WarehouseProduct.miqdor <= WarehouseProduct.min_threshold,
            ).order_by(WarehouseProduct.miqdor.asc()).limit(8)
        )).scalars().all()

        cat_rows = (await db.execute(
            select(WarehouseProduct.category, func.count(WarehouseProduct.id))
            .where(WarehouseProduct.is_active == True)
            .group_by(WarehouseProduct.category)
        )).all()
        cats = [(r[0].value if r[0] else "?", int(r[1] or 0)) for r in cat_rows]

        recent = (await db.execute(
            select(WarehouseLog, WarehouseProduct)
            .join(WarehouseProduct, WarehouseProduct.id == WarehouseLog.product_id)
            .order_by(WarehouseLog.created_at.desc()).limit(6)
        )).all()

    p = []
    p.append('<div class="hero"><div><div class="hero-greet">Assalomu alaykum,</div>')
    p.append('<div class="hero-name">' + h(name) + '</div>')
    p.append('<div class="hero-date">' + today.strftime("%d.%m.%Y") + '</div></div>'
             '<div class="hero-emoji">📦</div></div>')

    p.append('<div class="kpi-grid">')
    p.append('<div class="kpi"><div class="kpi-num kpi-blue">' + str(total) + '</div><div class="kpi-lbl">Jami mahsulot</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-orange">' + str(low_n) + '</div><div class="kpi-lbl">Kam qolgan</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-red">' + str(zero_n) + '</div><div class="kpi-lbl">Tugagan</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-green">' + str(today_ops) + '</div><div class="kpi-lbl">Bugun operatsiya</div></div>')
    p.append('</div>')

    p.append('<a href="/web/ombor-panel/operatsiya" class="big-btn">➕ Kirim / Chiqim qilish</a>')

    # Amallar (qo'shimcha funksiyalar)
    p.append('<div class="act-grid">')
    p.append('<a href="/web/ombor-panel/inventar" class="act-tile"><span class="act-ic">📋</span><span>Inventarizatsiya</span></a>')
    p.append('<a href="/web/ombor-panel/transfer" class="act-tile"><span class="act-ic">🔄</span><span>Transfer</span></a>')
    p.append('<a href="/web/ombor-panel/buyurtma" class="act-tile"><span class="act-ic">🛒</span><span>Buyurtma</span></a>')
    p.append('<a href="/web/ombor-panel/qoshish" class="act-tile"><span class="act-ic">➕</span><span>Yangi mahsulot</span></a>')
    p.append('</div>')

    if low_list:
        p.append('<div class="card"><div class="card-head"><h2>⚠️ Kam qolganlar</h2>'
                 '<span class="badge">' + str(len(low_list)) + '</span></div>')
        for pr in low_list:
            extra = " · ".join(filter(None, [pr.razmer, pr.rang, pr.qism]))
            p.append('<div class="row"><div><div class="row-name">' + h(pr.name) + '</div>')
            if extra:
                p.append('<div class="row-sub">' + h(extra) + '</div>')
            p.append('</div><div class="row-qty warn">' + ("%.0f" % float(pr.miqdor)) +
                     ' <span>' + h(pr.birlik or "dona") + '</span></div></div>')
        p.append('</div>')

    p.append('<div class="card"><div class="card-head"><h2>📦 Bo\'limlar</h2></div><div class="cat-grid">')
    for ck, cnt in cats:
        p.append('<a href="/web/ombor-panel/bolim/' + ck + '" class="cat-tile">'
                 '<div class="cat-name">' + CAT_LABELS.get(ck, ck) + '</div>'
                 '<div class="cat-cnt">' + str(cnt) + ' <span>dona</span></div></a>')
    p.append('</div></div>')

    if recent:
        p.append('<div class="card"><div class="card-head"><h2>📋 So\'nggi operatsiyalar</h2></div>')
        for log, pr in recent:
            d = float(log.delta or 0)
            is_in = d > 0
            icon = "📥" if is_in else "📤"
            cls = "op-in" if is_in else "op-out"
            sign = "+" if is_in else ""
            tm = log.created_at.strftime("%d.%m %H:%M") if log.created_at else ""
            p.append('<div class="row"><div class="op-ic ' + cls + '">' + icon + '</div>'
                     '<div style="flex:1"><div class="row-name">' + h(pr.name) + '</div>'
                     '<div class="row-sub">' + tm + '</div></div>'
                     '<div class="op-d ' + cls + '">' + sign + ("%.0f" % d) + '</div></div>')
        p.append('</div>')

    return web.Response(text=_base_ombor("Bosh", "home", "\n".join(p), name), content_type="text/html")


# ─── 2. KIRIM / CHIQIM ───────────────────────────────────────────────────
@_require_role("omborchi")
async def ombor_operatsiya(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    cat = request.query.get("cat", "")
    q = request.query.get("q", "").strip()
    sort = request.query.get("sort", "name")

    async with AsyncSessionLocal() as db:
        stmt = select(WarehouseProduct).where(WarehouseProduct.is_active == True)
        if cat:
            try:
                stmt = stmt.where(WarehouseProduct.category == ProductCategory(cat))
            except ValueError:
                pass
        if q:
            # Nom, razmer, rang bo'yicha qidiruv
            like = "%" + q + "%"
            stmt = stmt.where(
                WarehouseProduct.name.ilike(like)
                | WarehouseProduct.razmer.ilike(like)
                | WarehouseProduct.rang.ilike(like)
            )
        # Saralash
        if sort == "miqdor":
            stmt = stmt.order_by(WarehouseProduct.miqdor.asc())
        elif sort == "razmer":
            stmt = stmt.order_by(WarehouseProduct.razmer.asc().nulls_last(), WarehouseProduct.name.asc())
        else:
            stmt = stmt.order_by(WarehouseProduct.name.asc())
        products = (await db.execute(stmt.limit(80))).scalars().all()

        cat_rows = (await db.execute(
            select(WarehouseProduct.category, func.count(WarehouseProduct.id))
            .where(WarehouseProduct.is_active == True).group_by(WarehouseProduct.category)
        )).all()
        cats = [(r[0].value if r[0] else "?", int(r[1] or 0)) for r in cat_rows]

    p = []
    p.append('<h1>Kirim / Chiqim</h1>')
    p.append('<p class="muted">Nomi, razmer yoki rang bo\'yicha qidiring</p>')

    p.append('<form method="get" action="/web/ombor-panel/operatsiya" class="search-form">')
    if cat:
        p.append('<input type="hidden" name="cat" value="' + h(cat) + '">')
    p.append('<input type="text" name="q" value="' + h(q) + '" placeholder="Nom / razmer / rang..." class="search-input">')
    p.append('<button class="search-btn">🔍</button></form>')

    # Saralash tugmalari
    def _sort_link(key, label):
        on = "chip-on" if sort == key else ""
        url = "/web/ombor-panel/operatsiya?sort=" + key + (("&cat=" + cat) if cat else "") + (("&q=" + q) if q else "")
        return '<a href="' + url + '" class="chip ' + on + '">' + label + '</a>'
    p.append('<div class="chips">')
    p.append(_sort_link("name", "🔤 Nom"))
    p.append(_sort_link("miqdor", "📉 Kam qolgan"))
    p.append(_sort_link("razmer", "📐 Razmer"))
    p.append('</div>')

    p.append('<div class="chips">')
    p.append('<a href="/web/ombor-panel/operatsiya" class="chip ' + ("chip-on" if not cat else "") + '">Barchasi</a>')
    for ck, cnt in cats:
        on = "chip-on" if cat == ck else ""
        p.append('<a href="/web/ombor-panel/operatsiya?cat=' + ck + '" class="chip ' + on + '">'
                 + CAT_LABELS.get(ck, ck) + '</a>')
    p.append('</div>')

    if not products:
        p.append('<p class="empty">Mahsulot topilmadi</p>')
    else:
        for pr in products:
            extra = " · ".join(filter(None, [pr.razmer, pr.rang, pr.qism]))
            miq = float(pr.miqdor or 0)
            low = miq <= float(pr.min_threshold or 0)
            color = "#f87171" if low else ("#34d399" if miq > 0 else "#94a3b8")
            pid = str(pr.id)
            p.append('<div class="op-card" id="prod-' + pid + '">')
            p.append('<div class="op-top"><div><div class="op-name">' + h(pr.name) + '</div>')
            if extra:
                p.append('<div class="op-extra">' + h(extra) + '</div>')
            p.append('</div><div class="op-qty" style="color:' + color + '">'
                     + ("%.0f" % miq) + ' <span>' + h(pr.birlik or "dona") + '</span></div></div>')
            p.append('<div class="op-ctrl">'
                     '<input type="number" id="amt-' + pid + '" placeholder="Miqdor" class="op-amt" step="any" min="0">'
                     '<button class="op-b op-in-btn" onclick="doOp(' + pid + ',1)">+ Kirim</button>'
                     '<button class="op-b op-out-btn" onclick="doOp(' + pid + ',-1)">− Chiqim</button>'
                     '</div></div>')

    p.append(_OPS_JS)
    return web.Response(text=_base_ombor("Kirim/Chiqim", "ops", "\n".join(p), name), content_type="text/html")


# ─── 3. BO'LIMLAR ro'yxati (turlar bilan, admin uslubida) ────────────────
@_require_role("omborchi")
async def ombor_bolimlar(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    async with AsyncSessionLocal() as db:
        cat_rows = (await db.execute(
            select(
                WarehouseProduct.category,
                func.count(WarehouseProduct.id),
                sf.sum(sa_case((WarehouseProduct.miqdor <= WarehouseProduct.min_threshold, 1), else_=0)),
            ).where(WarehouseProduct.is_active == True).group_by(WarehouseProduct.category)
        )).all()
        counts = {(r[0].value if r[0] else "?"): (int(r[1] or 0), int(r[2] or 0)) for r in cat_rows}

    p = ['<h1>Ombor bo\'limlari</h1>',
         '<a href="/web/ombor-panel/qoshish" class="add-link">➕ Yangi mahsulot qo\'shish</a>']

    # _CAT_CFG tartibida — barcha bo'limlar va turlar soni
    for ck, cfg in _CAT_CFG.items():
        cnt, low = counts.get(ck, (0, 0))
        tur_count = len(cfg.get("turlar", {}))
        title = cfg.get("title", ck)
        low_badge = ('<span class="cat-warn">⚠️ ' + str(low) + '</span>') if low else '<span class="cat-ok">● OK</span>'
        p.append('<a href="/web/ombor-panel/bolim/' + ck + '" class="sec-row">')
        p.append('<div class="sec-name">' + title + '</div>')
        p.append('<div class="sec-meta">'
                 '<span class="sec-stat"><b>' + str(cnt) + '</b> mahsulot</span>'
                 '<span class="sec-stat"><b>' + str(tur_count) + '</b> tur</span>'
                 + low_badge + '</div>')
        p.append('</a>')

    p.append(_SEC_CSS)
    return web.Response(text=_base_ombor("Bo'limlar", "cats", "\n".join(p), name), content_type="text/html")


# ─── 4. BITTA BO'LIM — turlar bilan ──────────────────────────────────────
@_require_role("omborchi")
async def ombor_bolim(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    ck = request.match_info.get("cat", "")
    tur_filter = request.query.get("tur", "")
    cfg = _CAT_CFG.get(ck)
    if not cfg:
        return web.HTTPFound("/web/ombor-panel/bolimlar")
    try:
        cat_enum = ProductCategory(ck)
    except ValueError:
        return web.HTTPFound("/web/ombor-panel/bolimlar")

    turlar = cfg.get("turlar", {})

    async with AsyncSessionLocal() as db:
        stmt = select(WarehouseProduct).where(
            WarehouseProduct.is_active == True, WarehouseProduct.category == cat_enum
        )
        if tur_filter:
            stmt = stmt.where(WarehouseProduct.tur == tur_filter)
        products = (await db.execute(stmt.order_by(WarehouseProduct.name.asc()))).scalars().all()

        # Har tur bo'yicha mahsulot soni
        tur_rows = (await db.execute(
            select(WarehouseProduct.tur, func.count(WarehouseProduct.id))
            .where(WarehouseProduct.is_active == True, WarehouseProduct.category == cat_enum)
            .group_by(WarehouseProduct.tur)
        )).all()
        tur_counts = {(r[0] or ""): int(r[1] or 0) for r in tur_rows}

    p = ['<h1>' + cfg.get("title", ck) + '</h1>',
         '<p class="muted">' + str(len(products)) + ' ta mahsulot · ' + str(len(turlar)) + ' tur</p>']
    p.append('<a href="/web/ombor-panel/qoshish?cat=' + ck + '" class="add-link">➕ Bu bo\'limga mahsulot qo\'shish</a>')

    # Turlar filtri
    if turlar:
        p.append('<div class="chips">')
        all_on = "chip-on" if not tur_filter else ""
        p.append('<a href="/web/ombor-panel/bolim/' + ck + '" class="chip ' + all_on + '">Barchasi</a>')
        for tkey, tlabel in turlar.items():
            on = "chip-on" if tur_filter == tkey else ""
            c = tur_counts.get(tkey, 0)
            p.append('<a href="/web/ombor-panel/bolim/' + ck + '?tur=' + tkey + '" class="chip ' + on + '">'
                     + tlabel + ' (' + str(c) + ')</a>')
        p.append('</div>')

    if not products:
        p.append('<p class="empty">Bu turda mahsulot yo\'q. "➕ Mahsulot qo\'shish" orqali kiriting.</p>')
    else:
        # Qismli mahsulotlarni guruhlash: (nom, rang, tur) bir xil — bitta ramka.
        # RAZMER guruhga kirmaydi, chunki har qism o'z razmeriga ega.
        QISM_ORD = {"tepa": 0, "past": 1, "yon": 2, "paddo": 2}
        QISM_LBL = {"tepa": "TEPA", "past": "PAST", "yon": "YON", "paddo": "PADDO"}
        groups = {}
        order = []
        for pr in products:
            if pr.qism:
                key = (pr.name, pr.rang or "", pr.tur or "")
            else:
                key = ("__single__", str(pr.id))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(pr)

        for key in order:
            items = groups[key]
            if items[0].qism:
                items.sort(key=lambda x: QISM_ORD.get(x.qism or "", 9))
                first = items[0]
                tur_label = turlar.get(first.tur, first.tur or "")
                head_parts = list(filter(None, [tur_label, first.rang]))
                p.append('<div class="frame">')
                p.append('<div class="frame-head">' + h(first.name)
                         + (' <span class="frame-sub">' + h(" · ".join(head_parts)) + '</span>' if head_parts else '')
                         + '</div>')
                for pr in items:
                    miq = float(pr.miqdor or 0)
                    low = miq <= float(pr.min_threshold or 0)
                    color = "#f87171" if low else ("#34d399" if miq > 0 else "#94a3b8")
                    pid = str(pr.id)
                    qlbl = QISM_LBL.get(pr.qism or "", (pr.qism or "?").upper())
                    rz = (' <span class="frame-rz">' + h(pr.razmer) + '</span>') if pr.razmer else ''
                    p.append('<div class="frame-row" id="prod-' + pid + '">')
                    p.append('<div class="qism-tag">' + qlbl + rz + '</div>')
                    p.append('<div class="frame-qty" style="color:' + color + '">' + ("%.0f" % miq) +
                             ' <span>' + h(pr.birlik or "dona") + '</span></div>')
                    p.append('<input type="number" id="amt-' + pid + '" placeholder="0" class="frame-amt" step="any" min="0">')
                    p.append('<button class="fb fb-in" onclick="doOp(' + pid + ',1)">+</button>')
                    p.append('<button class="fb fb-out" onclick="doOp(' + pid + ',-1)">−</button>')
                    p.append('<a href="/web/ombor-panel/tahrir/' + pid + '" class="frame-edit">✏️</a>')
                    p.append('</div>')
                p.append('</div>')
            else:
                pr = items[0]
                tur_label = turlar.get(pr.tur, pr.tur or "")
                extra_parts = list(filter(None, [pr.razmer, pr.rang]))
                if tur_label:
                    extra_parts.insert(0, tur_label)
                extra = " · ".join(extra_parts)
                miq = float(pr.miqdor or 0)
                low = miq <= float(pr.min_threshold or 0)
                color = "#f87171" if low else ("#34d399" if miq > 0 else "#94a3b8")
                pid = str(pr.id)
                p.append('<div class="op-card" id="prod-' + pid + '">')
                p.append('<div class="op-top"><div><div class="op-name">' + h(pr.name) + '</div>')
                if extra:
                    p.append('<div class="op-extra">' + h(extra) + '</div>')
                p.append('</div><a href="/web/ombor-panel/tahrir/' + pid + '" class="edit-link">✏️</a>'
                         '<div class="op-qty" style="color:' + color + '">'
                         + ("%.0f" % miq) + ' <span>' + h(pr.birlik or "dona") + '</span></div></div>')
                p.append('<div class="op-ctrl">'
                         '<input type="number" id="amt-' + pid + '" placeholder="Miqdor" class="op-amt" step="any" min="0">'
                         '<button class="op-b op-in-btn" onclick="doOp(' + pid + ',1)">+ Kirim</button>'
                         '<button class="op-b op-out-btn" onclick="doOp(' + pid + ',-1)">− Chiqim</button>'
                         '</div></div>')
    p.append(_FRAME_CSS)
    p.append(_OPS_JS)
    p.append(_SEC_CSS)
    return web.Response(text=_base_ombor(cfg.get("title", ck), "cats", "\n".join(p), name), content_type="text/html")


# ─── 5. TARIX ────────────────────────────────────────────────────────────
@_require_role("omborchi")
async def ombor_tarix(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(WarehouseLog, WarehouseProduct)
            .join(WarehouseProduct, WarehouseProduct.id == WarehouseLog.product_id)
            .order_by(WarehouseLog.created_at.desc()).limit(50)
        )).all()

    p = ['<h1>Operatsiyalar tarixi</h1>', '<p class="muted">So\'nggi 50 ta</p>']
    if not rows:
        p.append('<p class="empty">Hali operatsiya yo\'q</p>')
    else:
        p.append('<div class="card">')
        for log, pr in rows:
            d = float(log.delta or 0)
            is_in = d > 0
            icon = "📥" if is_in else "📤"
            cls = "op-in" if is_in else "op-out"
            sign = "+" if is_in else ""
            tm = log.created_at.strftime("%d.%m.%Y %H:%M") if log.created_at else ""
            izoh = (" · " + h(log.izoh)) if log.izoh else ""
            p.append('<div class="row"><div class="op-ic ' + cls + '">' + icon + '</div>'
                     '<div style="flex:1"><div class="row-name">' + h(pr.name) + '</div>'
                     '<div class="row-sub">' + tm + izoh + '</div></div>'
                     '<div class="op-d ' + cls + '">' + sign + ("%.0f" % d) + '</div></div>')
        p.append('</div>')
    return web.Response(text=_base_ombor("Tarix", "history", "\n".join(p), name), content_type="text/html")


_FRAME_CSS = """
<style>
.frame { background:var(--bg2); border:2px solid var(--accent); border-radius:14px; padding:12px; margin-bottom:12px }
.frame-head { font-weight:700; font-size:15px; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid var(--border) }
.frame-sub { font-size:12px; color:var(--muted); font-weight:400 }
.frame-row { display:flex; align-items:center; gap:8px; padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.05) }
.frame-row:last-child { border-bottom:none }
.qism-tag { min-width:54px; font-size:12px; font-weight:800; color:#a5b4fc; background:rgba(99,102,241,0.15); border-radius:6px; padding:4px 6px; text-align:center }
.frame-rz { display:block; font-size:9px; color:var(--muted); font-weight:600; margin-top:2px }
.frame-qty { min-width:62px; font-weight:800; font-size:15px }
.frame-qty span { font-size:10px; color:var(--muted); font-weight:400 }
.frame-amt { width:56px; padding:8px; border-radius:8px; border:1px solid var(--border); background:var(--bg); color:var(--fg); font-size:14px }
.fb { width:34px; height:34px; border:none; border-radius:8px; font-weight:800; font-size:18px; cursor:pointer; color:#fff }
.fb-in { background:#10b981 } .fb-out { background:#f59e0b }
.frame-edit { text-decoration:none; font-size:17px; margin-left:auto }
</style>
"""


_SEC_CSS = """
<style>
.sec-row { display:flex; justify-content:space-between; align-items:center; gap:10px;
  background:var(--bg2); border:1px solid var(--border); border-radius:14px; padding:16px;
  margin-bottom:10px; text-decoration:none; color:var(--fg) }
.sec-row:active { border-color:var(--accent) }
.sec-name { font-weight:700; font-size:15px }
.sec-meta { display:flex; align-items:center; gap:12px; flex-wrap:wrap; justify-content:flex-end }
.sec-stat { font-size:12px; color:var(--muted) }
.sec-stat b { color:#60a5fa; font-size:15px }
.cat-ok { color:#34d399; font-size:12px; font-weight:700 }
</style>
"""


# ─── JS (kirim/chiqim) ───────────────────────────────────────────────────
_OPS_JS = (
    '<script>'
    'function doOp(pid,sign){'
    'var inp=document.getElementById("amt-"+pid);'
    'var val=parseFloat(inp.value);'
    'if(!val||val<=0){alert("Miqdor kiriting");inp.focus();return;}'
    'var url=sign>0?"/web/warehouse/kirim":"/web/warehouse/chiqim";'
    'var izoh=sign>0?"Ombor panel - kirim":"Ombor panel - chiqim";'
    'var btn=event.target;'
    'fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({product_id:pid,miqdor:val,izoh:izoh})})'
    '.then(function(r){return r.json();}).then(function(d){'
    'if(d.ok){var item=document.getElementById("prod-"+pid);'
    'var qty=item.querySelector(".op-qty");'
    'qty.innerHTML=Math.round(d.new_miqdor)+" <span>dona</span>";'
    'qty.style.color=sign>0?"#34d399":"#fbbf24";'
    'inp.value="";var old=btn.textContent;btn.textContent="✓ Saqlandi";'
    'setTimeout(function(){btn.textContent=old;qty.style.color="";},1200);'
    '}else{alert("Xato: "+(d.error||"?"));}'
    '}).catch(function(e){alert("Tarmoq xatosi: "+e);});}'
    '</script>'
)


# ─── CSS (mustaqil, mobil-birinchi) ──────────────────────────────────────
_OMBOR_CSS = """
<style>
* { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent }
:root {
  --bg:#0f172a; --bg2:#1e293b; --card:#1e293b; --fg:#f1f5f9;
  --muted:#94a3b8; --border:#334155; --accent:#6366f1;
}
body { font-family:-apple-system,'Segoe UI',Roboto,sans-serif; background:var(--bg); color:var(--fg); padding-bottom:80px; }
.top-bar { position:sticky; top:0; z-index:50; display:flex; justify-content:space-between; align-items:center;
  background:var(--bg2); border-bottom:1px solid var(--border); padding:12px 16px; }
.tb-left { display:flex; align-items:center; gap:10px }
.tb-logo { font-size:26px }
.tb-title { font-weight:800; font-size:15px }
.tb-sub { font-size:12px; color:var(--muted) }
.tb-logout { color:#f87171; text-decoration:none; font-size:13px; font-weight:600;
  padding:6px 12px; border:1px solid rgba(248,113,113,0.3); border-radius:8px }
.content { padding:16px; max-width:760px; margin:0 auto }
h1 { font-size:22px; margin-bottom:4px }
.muted { color:var(--muted); font-size:14px; margin-bottom:16px }
.empty { text-align:center; color:var(--muted); padding:40px }

.hero { display:flex; justify-content:space-between; align-items:center;
  background:linear-gradient(135deg,#6366f1,#8b5cf6); border-radius:18px; padding:22px; color:#fff; margin-bottom:18px; }
.hero-greet { font-size:14px; opacity:0.9 }
.hero-name { font-size:22px; font-weight:800 }
.hero-date { font-size:13px; opacity:0.85; margin-top:2px }
.hero-emoji { font-size:46px }

.kpi-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; margin-bottom:16px }
.kpi { background:var(--bg2); border:1px solid var(--border); border-radius:16px; padding:18px; text-align:center }
.kpi-num { font-size:32px; font-weight:800; line-height:1 }
.kpi-lbl { font-size:12px; color:var(--muted); margin-top:6px; font-weight:600 }
.kpi-blue{color:#60a5fa} .kpi-orange{color:#fbbf24} .kpi-red{color:#f87171} .kpi-green{color:#34d399}

.big-btn { display:block; text-align:center; background:linear-gradient(135deg,#10b981,#059669);
  color:#fff; text-decoration:none; padding:18px; border-radius:16px; font-weight:800; font-size:17px; margin-bottom:18px;
  box-shadow:0 8px 24px rgba(16,185,129,0.3); }
.big-btn:active { transform:scale(0.98) }

.act-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; margin-bottom:18px }
.act-tile { display:flex; flex-direction:column; align-items:center; gap:8px; text-decoration:none;
  background:var(--bg2); border:1px solid var(--border); border-radius:14px; padding:18px 10px;
  color:var(--fg); font-size:13px; font-weight:600; text-align:center }
.act-tile:active { border-color:var(--accent) }
.act-ic { font-size:28px }
.inv-diff { margin-top:8px; font-size:13px; font-weight:700; text-align:right }

.card { background:var(--bg2); border:1px solid var(--border); border-radius:16px; padding:16px; margin-bottom:14px }
.card-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px }
.card-head h2 { font-size:16px }
.badge { background:#f59e0b; color:#fff; border-radius:20px; padding:2px 12px; font-size:13px; font-weight:700 }

.row { display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1px solid var(--border) }
.row:last-child { border-bottom:none }
.row-name { font-weight:600; font-size:14px }
.row-sub { font-size:12px; color:var(--muted); margin-top:2px }
.row-qty { font-size:20px; font-weight:800; margin-left:auto; white-space:nowrap }
.row-qty span { font-size:11px; color:var(--muted); font-weight:400 }
.row-qty.warn { color:#fbbf24 }

.cat-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px }
.cat-tile { display:block; text-decoration:none; background:var(--bg); border:1px solid var(--border);
  border-radius:14px; padding:16px; position:relative }
.cat-tile:active { border-color:var(--accent) }
.cat-name { font-size:14px; font-weight:700; color:var(--fg); margin-bottom:6px }
.cat-cnt { font-size:22px; font-weight:800; color:#60a5fa }
.cat-cnt span { font-size:11px; color:var(--muted); font-weight:400 }
.cat-warn { position:absolute; top:10px; right:10px; background:rgba(245,158,11,0.2); color:#fbbf24;
  border-radius:8px; padding:2px 8px; font-size:11px; font-weight:700 }
.add-link { display:block; text-align:center; background:linear-gradient(135deg,#6366f1,#4f46e5);
  color:#fff; text-decoration:none; padding:14px; border-radius:12px; font-weight:700; font-size:15px; margin-bottom:16px }
.edit-link { font-size:20px; text-decoration:none; padding:4px 8px; margin-left:auto; align-self:flex-start }

.op-ic { font-size:18px; width:34px; height:34px; display:flex; align-items:center; justify-content:center; border-radius:9px }
.op-in { background:rgba(16,185,129,0.15) }
.op-out { background:rgba(239,68,68,0.15) }
.op-d { font-weight:800; font-size:16px; margin-left:auto }
.op-d.op-in { color:#34d399 } .op-d.op-out { color:#f87171 }

.search-form { display:flex; gap:8px; margin-bottom:14px }
.search-input { flex:1; padding:13px 15px; border-radius:12px; border:1px solid var(--border);
  background:var(--bg2); color:var(--fg); font-size:15px }
.search-btn { padding:13px 18px; border:none; border-radius:12px; background:var(--accent); color:#fff; font-size:16px; cursor:pointer }
.chips { display:flex; gap:8px; overflow-x:auto; padding-bottom:10px; margin-bottom:16px; -webkit-overflow-scrolling:touch }
.chip { white-space:nowrap; padding:8px 14px; border-radius:20px; background:var(--bg2);
  border:1px solid var(--border); color:var(--fg); text-decoration:none; font-size:13px; font-weight:600 }
.chip-on { background:var(--accent); color:#fff; border-color:var(--accent) }

.op-card { background:var(--bg2); border:1px solid var(--border); border-radius:14px; padding:14px; margin-bottom:10px }
.op-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px }
.op-name { font-weight:700; font-size:15px }
.op-extra { font-size:12px; color:var(--muted); margin-top:2px }
.op-qty { font-size:22px; font-weight:800; white-space:nowrap }
.op-qty span { font-size:12px; color:var(--muted); font-weight:400 }
.op-ctrl { display:flex; gap:8px }
.op-amt { flex:1; min-width:0; padding:12px; border-radius:10px; border:1px solid var(--border); background:var(--bg); color:var(--fg); font-size:16px }
.op-b { padding:12px 14px; border:none; border-radius:10px; font-weight:700; font-size:14px; cursor:pointer; white-space:nowrap }
.op-in-btn { background:linear-gradient(135deg,#10b981,#059669); color:#fff }
.op-out-btn { background:linear-gradient(135deg,#f59e0b,#d97706); color:#fff }
.op-b:active { transform:scale(0.95) }

.bottom-nav { position:fixed; bottom:0; left:0; right:0; z-index:50; display:flex;
  background:var(--bg2); border-top:1px solid var(--border); padding:6px 0 calc(6px + env(safe-area-inset-bottom)); }
.bnav-item { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px;
  text-decoration:none; color:var(--muted); padding:6px 0; font-size:11px; font-weight:600 }
.bnav-icon { font-size:22px }
.nav-active { color:var(--accent) }
.nav-active .bnav-icon { transform:translateY(-1px) }

@media (min-width:760px) { .kpi-grid { grid-template-columns:repeat(4,1fr) } }
</style>
"""


# ─── 6. YANGI MAHSULOT QO'SHISH ──────────────────────────────────────────
@_require_role("omborchi")
async def ombor_qoshish(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    msg = request.query.get("msg", "")
    pre_cat = request.query.get("cat", "")

    import json as _json
    cat_options = ""
    for ck, cfg in _CAT_CFG.items():
        sel = " selected" if ck == pre_cat else ""
        cat_options += '<option value="' + ck + '"' + sel + '>' + cfg.get("title", ck) + '</option>'
    # Turlar JS uchun
    turlar_js = _json.dumps({ck: cfg.get("turlar", {}) for ck, cfg in _CAT_CFG.items()}, ensure_ascii=False)

    p = ['<h1>Yangi mahsulot</h1>', '<p class="muted">Omborga yangi mahsulot qo\'shish</p>']
    if msg == "ok":
        p.append('<div class="ok-msg">✅ Mahsulot qo\'shildi! Yana qo\'shishingiz mumkin.</div>')

    p.append('<form method="post" action="/web/ombor-panel/qoshish" class="add-form">')
    p.append('<label>Bo\'lim (kategoriya) *</label>'
             '<select name="category" id="cat" class="fld" onchange="updTur()" required>' + cat_options + '</select>')
    p.append('<label>Tur</label><select name="tur" id="tur" class="fld"></select>')

    # Mahsulot ko'rinishi: Oddiy / Adyol (3 qism) / Pastel (3 qism)
    p.append('<label>Mahsulot ko\'rinishi</label>'
             '<select name="kind" id="kind" class="fld" onchange="updKind()">'
             '<option value="oddiy">Oddiy (bitta mahsulot)</option>'
             '<option value="adyol">Adyol — 3 qism (TEPA, PAST, YON)</option>'
             '<option value="pastel">Pastel — 3 qism (TEPA, PAST, PADDO)</option>'
             '</select>')

    p.append('<label>Nomi *</label><input name="name" class="fld" placeholder="Masalan: Istanbul adyol Katta" required>')
    p.append('<div class="frow">'
             '<div><label>Razmer</label><input name="razmer" class="fld" placeholder="98x62"></div>'
             '<div><label>Rang</label><input name="rang" class="fld" placeholder="oq"></div></div>')
    p.append('<div class="frow">'
             '<div><label>Gramaj (g/m²) — rulon/gofra uchun</label><input name="gramaj" type="number" step="any" class="fld" placeholder="120"></div>'
             '<div><label>Birlik</label><select name="birlik" class="fld">'
             '<option value="dona">dona</option><option value="kg">kg</option>'
             '<option value="gramm">gramm</option><option value="m3">m³</option>'
             '<option value="metr">metr</option><option value="pachka">pachka</option>'
             '<option value="rulon">rulon</option><option value="quti">quti</option>'
             '</select></div></div>')
    p.append('<div class="frow">'
             '<div id="miqdor-box"><label>Boshlang\'ich miqdor</label><input name="miqdor" id="miqdor" type="number" step="any" class="fld" value="0"></div></div>')

    # Adyol/pastel 3 qism — har qism O'Z razmeri va soni bilan
    p.append('<div id="qism-box" style="display:none">'
             '<div class="qism-title">Har qism — o\'z razmeri va soni:</div>'
             '<div class="qrow"><div class="qlbl">TEPA</div>'
             '<input name="razmer_tepa" class="fld qfld" placeholder="razmer (mas: 98x62)">'
             '<input name="qism_tepa" type="number" step="any" class="fld qfld" placeholder="soni" value="0"></div>'
             '<div class="qrow"><div class="qlbl">PAST</div>'
             '<input name="razmer_past" class="fld qfld" placeholder="razmer">'
             '<input name="qism_past" type="number" step="any" class="fld qfld" placeholder="soni" value="0"></div>'
             '<div class="qrow"><div class="qlbl" id="q3-lbl">YON</div>'
             '<input name="razmer_3" class="fld qfld" placeholder="razmer">'
             '<input name="qism_3" type="number" step="any" class="fld qfld" placeholder="soni" value="0"></div>'
             '<div class="muted2">Har qism alohida ombor yozuvi bo\'ladi, lekin bitta ramkada ko\'rinadi. Razmer bo\'sh bo\'lsa — yuqoridagi umumiy razmer ishlatiladi.</div></div>')

    p.append('<div class="frow">'
             '<div><label>Kam chegarasi (qizil)</label><input name="min_threshold" type="number" step="any" class="fld" value="10"></div>'
             '<div><label>Ogoh chegarasi (sariq)</label><input name="yellow_threshold" type="number" step="any" class="fld" value="20"></div></div>')
    p.append('<button class="save-btn">💾 Qo\'shish</button></form>')

    p.append('<script>var TURLAR=' + turlar_js + ';'
             'function updTur(){var c=document.getElementById("cat").value;'
             'var sel=document.getElementById("tur");var ts=TURLAR[c]||{};'
             'sel.innerHTML="<option value=\\"\\">— tur tanlanmagan —</option>";'
             'for(var k in ts){var o=document.createElement("option");o.value=k;o.textContent=ts[k];sel.appendChild(o);}}'
             'function updKind(){var k=document.getElementById("kind").value;'
             'var qbox=document.getElementById("qism-box");var mbox=document.getElementById("miqdor-box");'
             'if(k==="oddiy"){qbox.style.display="none";mbox.style.display="block";}'
             'else{qbox.style.display="block";mbox.style.display="none";'
             'document.getElementById("q3-lbl").textContent=(k==="pastel")?"PADDO":"YON";}}'
             'updTur();updKind();</script>')
    p.append(_ADD_CSS)
    return web.Response(text=_base_ombor("Qo'shish", "add", "\n".join(p), name), content_type="text/html")


@_require_role("omborchi")
async def ombor_qoshish_post(request: web.Request):
    data = await request.post()
    try:
        cat = ProductCategory(data.get("category"))
    except ValueError:
        return web.HTTPFound("/web/ombor-panel/qoshish")
    name_v = (data.get("name") or "").strip()
    if not name_v:
        return web.HTTPFound("/web/ombor-panel/qoshish")

    def _f(key, default=0.0):
        try:
            return float(data.get(key) or default)
        except (ValueError, TypeError):
            return default

    kind = (data.get("kind") or "oddiy").strip()
    def _gram():
        try:
            g = (data.get("gramaj") or "").strip()
            return float(g) if g else None
        except (ValueError, TypeError):
            return None
    base = dict(
        category=cat,
        name=name_v,
        tur=(data.get("tur") or "").strip() or None,
        razmer=(data.get("razmer") or "").strip() or None,
        rang=(data.get("rang") or "").strip() or None,
        qalinlik=_gram(),
        birlik=(data.get("birlik") or "dona").strip(),
        min_threshold=_f("min_threshold", 10),
        yellow_threshold=_f("yellow_threshold", 20),
        is_active=True,
    )

    async with AsyncSessionLocal() as db:
        if kind in ("adyol", "pastel"):
            # 3 qism — har biri O'Z razmeri bilan, alohida yozuv
            third_qism = "paddo" if kind == "pastel" else "yon"
            common_razmer = (data.get("razmer") or "").strip() or None
            def _rz(key):
                return (data.get(key) or "").strip() or common_razmer
            qismlar = [
                ("tepa", _rz("razmer_tepa"), _f("qism_tepa", 0)),
                ("past", _rz("razmer_past"), _f("qism_past", 0)),
                (third_qism, _rz("razmer_3"), _f("qism_3", 0)),
            ]
            for qism, rz, miq in qismlar:
                row = dict(base)
                row["razmer"] = rz
                db.add(WarehouseProduct(qism=qism, miqdor=miq, **row))
        else:
            db.add(WarehouseProduct(miqdor=_f("miqdor", 0), **base))
        await db.commit()
    cat_key = data.get("category") or ""
    raise web.HTTPFound("/web/ombor-panel/qoshish?msg=ok&cat=" + cat_key)


# ─── 7. MAHSULOT TAHRIRLASH ──────────────────────────────────────────────
@_require_role("omborchi")
async def ombor_tahrir(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    try:
        pid = int(request.match_info.get("id", "0"))
    except ValueError:
        pid = 0
    async with AsyncSessionLocal() as db:
        pr = await db.get(WarehouseProduct, pid)
        if not pr:
            return web.HTTPFound("/web/ombor-panel/bolimlar")

    p = ['<h1>Tahrirlash</h1>', '<p class="muted">' + h(pr.name) + '</p>']
    p.append('<form method="post" action="/web/ombor-panel/tahrir/' + str(pid) + '" class="add-form">')
    p.append('<label>Nomi</label><input name="name" class="fld" value="' + h(pr.name) + '" required>')
    p.append('<div class="frow">'
             '<div><label>Razmer</label><input name="razmer" class="fld" value="' + h(pr.razmer or "") + '"></div>'
             '<div><label>Rang</label><input name="rang" class="fld" value="' + h(pr.rang or "") + '"></div></div>')
    # Gramaj + birlik
    _bsel = lambda u: " selected" if (pr.birlik or "dona") == u else ""
    p.append('<div class="frow">'
             '<div><label>Gramaj (g/m²)</label><input name="gramaj" type="number" step="any" class="fld" value="' + (str(pr.qalinlik) if pr.qalinlik is not None else "") + '"></div>'
             '<div><label>Birlik</label><select name="birlik" class="fld">'
             '<option value="dona"' + _bsel("dona") + '>dona</option>'
             '<option value="kg"' + _bsel("kg") + '>kg</option>'
             '<option value="gramm"' + _bsel("gramm") + '>gramm</option>'
             '<option value="m3"' + _bsel("m3") + '>m³</option>'
             '<option value="metr"' + _bsel("metr") + '>metr</option>'
             '<option value="pachka"' + _bsel("pachka") + '>pachka</option>'
             '<option value="rulon"' + _bsel("rulon") + '>rulon</option>'
             '<option value="quti"' + _bsel("quti") + '>quti</option>'
             '</select></div></div>')
    # Qism (agar bor bo'lsa — adyol/pastel)
    if pr.qism:
        _qsel = lambda q: " selected" if (pr.qism or "") == q else ""
        p.append('<label>Qism</label><select name="qism" class="fld">'
                 '<option value="tepa"' + _qsel("tepa") + '>TEPA</option>'
                 '<option value="past"' + _qsel("past") + '>PAST</option>'
                 '<option value="yon"' + _qsel("yon") + '>YON</option>'
                 '<option value="paddo"' + _qsel("paddo") + '>PADDO</option>'
                 '</select>')
    p.append('<div class="frow">'
             '<div><label>Kam chegarasi</label><input name="min_threshold" type="number" step="any" class="fld" value="' + str(pr.min_threshold or 0) + '"></div>'
             '<div><label>Ogoh chegarasi</label><input name="yellow_threshold" type="number" step="any" class="fld" value="' + str(pr.yellow_threshold or 0) + '"></div></div>')
    p.append('<button class="save-btn">💾 Saqlash</button></form>')
    p.append('<a href="/web/ombor-panel/ochirish/' + str(pid) + '" class="del-btn" '
             'onclick="return confirm(\'Bu mahsulotni butunlay o\\\'chirmoqchimisiz?\')">🗑 Mahsulotni o\'chirish</a>')
    p.append(_ADD_CSS)
    return web.Response(text=_base_ombor("Tahrir", "cats", "\n".join(p), name), content_type="text/html")


@_require_role("omborchi")
async def ombor_tahrir_post(request: web.Request):
    try:
        pid = int(request.match_info.get("id", "0"))
    except ValueError:
        pid = 0
    data = await request.post()

    def _f(key, cur):
        try:
            return float(data.get(key))
        except (ValueError, TypeError):
            return cur

    async with AsyncSessionLocal() as db:
        pr = await db.get(WarehouseProduct, pid)
        if pr:
            nm = (data.get("name") or "").strip()
            if nm:
                pr.name = nm
            pr.razmer = (data.get("razmer") or "").strip() or None
            pr.rang = (data.get("rang") or "").strip() or None
            # Gramaj
            _g = (data.get("gramaj") or "").strip()
            if _g != "":
                try:
                    pr.qalinlik = float(_g.replace(",", "."))
                except ValueError:
                    pass
            # Birlik
            _b = (data.get("birlik") or "").strip()
            if _b:
                pr.birlik = _b
            # Qism (agar formada bo'lsa)
            _q = (data.get("qism") or "").strip()
            if _q:
                pr.qism = _q
            pr.min_threshold = _f("min_threshold", pr.min_threshold)
            pr.yellow_threshold = _f("yellow_threshold", pr.yellow_threshold)
            await db.commit()
            cat_key = pr.category.value if pr.category else ""
    raise web.HTTPFound("/web/ombor-panel/bolim/" + (cat_key or ""))


@_require_role("omborchi")
async def ombor_ochirish(request: web.Request):
    try:
        pid = int(request.match_info.get("id", "0"))
    except ValueError:
        pid = 0
    cat_key = ""
    async with AsyncSessionLocal() as db:
        pr = await db.get(WarehouseProduct, pid)
        if pr:
            pr.is_active = False
            cat_key = pr.category.value if pr.category else ""
            await db.commit()
    raise web.HTTPFound("/web/ombor-panel/bolim/" + cat_key if cat_key else "/web/ombor-panel/bolimlar")


_ADD_CSS = """
<style>
.add-form { display:flex; flex-direction:column; gap:6px }
.add-form label { font-size:13px; color:var(--muted); font-weight:600; margin-top:8px }
.fld { padding:12px 14px; border-radius:10px; border:1px solid var(--border); background:var(--bg2); color:var(--fg); font-size:15px; width:100% }
.frow { display:flex; gap:10px }
.frow > div { flex:1 }
.frow3 { display:flex; gap:8px }
.frow3 > div { flex:1 }
.qism-box, #qism-box { background:rgba(99,102,241,0.08); border:1px solid rgba(99,102,241,0.3); border-radius:12px; padding:12px; margin-top:6px }
.qism-title { font-size:13px; font-weight:700; color:#a5b4fc; margin-bottom:8px }
.qrow { display:flex; gap:6px; align-items:center; margin-bottom:6px }
.qlbl { min-width:50px; font-size:12px; font-weight:800; color:#a5b4fc; background:rgba(99,102,241,0.15); border-radius:6px; padding:8px 4px; text-align:center }
.qfld { flex:1 }
.muted2 { font-size:11px; color:var(--muted); margin-top:6px }
.save-btn { margin-top:16px; padding:15px; border:none; border-radius:12px; background:linear-gradient(135deg,#10b981,#059669); color:#fff; font-weight:800; font-size:16px; cursor:pointer }
.del-btn { display:block; text-align:center; margin-top:12px; padding:14px; border-radius:12px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.4); color:#f87171; text-decoration:none; font-weight:700 }
.ok-msg { background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.4); color:#34d399; padding:14px; border-radius:12px; font-weight:700; text-align:center; margin-bottom:16px }
</style>
"""


# ─── 8. HISOBOT (kirim/chiqim, ombor holati) ─────────────────────────────
@_require_role("omborchi")
async def ombor_hisobot(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    period = request.query.get("period", "week")
    today = date.today()
    if period == "today":
        start = today; plabel = "Bugun"
    elif period == "month":
        start = today.replace(day=1); plabel = "Bu oy"
    else:
        from datetime import timedelta
        start = today - timedelta(days=7); plabel = "So'nggi 7 kun"

    async with AsyncSessionLocal() as db:
        # Kirim/chiqim jami (davr bo'yicha)
        logs = (await db.execute(
            select(WarehouseLog).where(func.date(WarehouseLog.created_at) >= start)
        )).scalars().all()
        total_kirim = sum(float(l.miqdor or 0) for l in logs if (float(l.keyin or 0) - float(l.oldin or 0)) > 0)
        total_chiqim = sum(float(l.miqdor or 0) for l in logs if (float(l.keyin or 0) - float(l.oldin or 0)) < 0)
        op_count = len(logs)

        # Bo'limlar bo'yicha joriy holat
        cat_rows = (await db.execute(
            select(
                WarehouseProduct.category,
                func.count(WarehouseProduct.id),
                func.coalesce(func.sum(WarehouseProduct.miqdor), 0),
                sf.sum(sa_case((WarehouseProduct.miqdor <= WarehouseProduct.min_threshold, 1), else_=0)),
            ).where(WarehouseProduct.is_active == True).group_by(WarehouseProduct.category)
        )).all()
        cats = [(r[0].value if r[0] else "?", int(r[1] or 0), float(r[2] or 0), int(r[3] or 0)) for r in cat_rows]

        total_items = sum(c[1] for c in cats)
        total_units = sum(c[2] for c in cats)
        total_low = sum(c[3] for c in cats)

        # Eng faol mahsulotlar (ko'p harakatlangan)
        active_rows = (await db.execute(
            select(WarehouseProduct.name, func.count(WarehouseLog.id))
            .join(WarehouseLog, WarehouseLog.product_id == WarehouseProduct.id)
            .where(func.date(WarehouseLog.created_at) >= start)
            .group_by(WarehouseProduct.id, WarehouseProduct.name)
            .order_by(func.count(WarehouseLog.id).desc()).limit(6)
        )).all()

    p = []
    p.append('<h1>Hisobotlar</h1>')
    p.append('<p class="muted">' + plabel + '</p>')

    # Davr filtri
    p.append('<div class="chips">')
    for key, label in [("today", "Bugun"), ("week", "Hafta"), ("month", "Oy")]:
        on = "chip-on" if period == key else ""
        p.append('<a href="/web/ombor-panel/hisobot?period=' + key + '" class="chip ' + on + '">' + label + '</a>')
    p.append('</div>')

    # Kirim/chiqim KPI
    p.append('<div class="card"><div class="card-head"><h2>📈 Harakat (' + plabel + ')</h2></div>')
    p.append('<div class="kpi-grid">')
    p.append('<div class="kpi"><div class="kpi-num kpi-green">+' + ("%.0f" % total_kirim) + '</div><div class="kpi-lbl">Kirim</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-red">−' + ("%.0f" % total_chiqim) + '</div><div class="kpi-lbl">Chiqim</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-blue">' + str(op_count) + '</div><div class="kpi-lbl">Operatsiya</div></div>')
    p.append('</div></div>')

    # Ombor umumiy holati
    p.append('<div class="card"><div class="card-head"><h2>📦 Ombor holati</h2></div>')
    p.append('<div class="kpi-grid">')
    p.append('<div class="kpi"><div class="kpi-num kpi-blue">' + str(total_items) + '</div><div class="kpi-lbl">Tur</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-green">' + ("%.0f" % total_units) + '</div><div class="kpi-lbl">Jami birlik</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-orange">' + str(total_low) + '</div><div class="kpi-lbl">Kam qolgan</div></div>')
    p.append('</div></div>')

    # Bo'limlar bo'yicha jadval
    p.append('<div class="card"><div class="card-head"><h2>🏭 Bo\'limlar bo\'yicha</h2></div>')
    if cats:
        for ck, cnt, units, low in cats:
            warn = (' · <span style="color:#fbbf24">⚠️ ' + str(low) + ' kam</span>') if low else ''
            p.append('<div class="row"><div style="flex:1"><div class="row-name">' + CAT_LABELS.get(ck, ck) + '</div>'
                     '<div class="row-sub">' + str(cnt) + ' tur' + warn + '</div></div>'
                     '<div class="row-qty">' + ("%.0f" % units) + ' <span>birlik</span></div></div>')
    else:
        p.append('<p class="empty">Ma\'lumot yo\'q</p>')
    p.append('</div>')

    # Eng faol mahsulotlar
    if active_rows:
        p.append('<div class="card"><div class="card-head"><h2>🔥 Eng faol mahsulotlar</h2></div>')
        for nm, c in active_rows:
            p.append('<div class="row"><div style="flex:1"><div class="row-name">' + h(nm) + '</div></div>'
                     '<div class="row-qty">' + str(int(c)) + ' <span>operatsiya</span></div></div>')
        p.append('</div>')

    return web.Response(text=_base_ombor("Hisobot", "report", "\n".join(p), name), content_type="text/html")


# ─── 9. INVENTARIZATSIYA (haqiqiy sanab, tuzatish) ───────────────────────
@_require_role("omborchi")
async def ombor_inventar(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    cat = request.query.get("cat", "")
    q = request.query.get("q", "").strip()

    async with AsyncSessionLocal() as db:
        stmt = select(WarehouseProduct).where(WarehouseProduct.is_active == True)
        if cat:
            try:
                stmt = stmt.where(WarehouseProduct.category == ProductCategory(cat))
            except ValueError:
                pass
        if q:
            like = "%" + q + "%"
            stmt = stmt.where(WarehouseProduct.name.ilike(like) | WarehouseProduct.razmer.ilike(like))
        products = (await db.execute(stmt.order_by(WarehouseProduct.name.asc()).limit(80))).scalars().all()
        cat_rows = (await db.execute(
            select(WarehouseProduct.category, func.count(WarehouseProduct.id))
            .where(WarehouseProduct.is_active == True).group_by(WarehouseProduct.category)
        )).all()
        cats = [(r[0].value if r[0] else "?", int(r[1] or 0)) for r in cat_rows]

    p = ['<h1>📋 Inventarizatsiya</h1>',
         '<p class="muted">Haqiqiy sanab, miqdorni to\'g\'rilang. Farq avtomatik hisoblanadi.</p>']
    p.append('<form method="get" action="/web/ombor-panel/inventar" class="search-form">')
    p.append('<input type="text" name="q" value="' + h(q) + '" placeholder="Mahsulot qidirish..." class="search-input">')
    p.append('<button class="search-btn">🔍</button></form>')
    p.append('<div class="chips">')
    p.append('<a href="/web/ombor-panel/inventar" class="chip ' + ("chip-on" if not cat else "") + '">Barchasi</a>')
    for ck, cnt in cats:
        on = "chip-on" if cat == ck else ""
        p.append('<a href="/web/ombor-panel/inventar?cat=' + ck + '" class="chip ' + on + '">' + CAT_LABELS.get(ck, ck) + '</a>')
    p.append('</div>')

    if not products:
        p.append('<p class="empty">Mahsulot topilmadi</p>')
    else:
        for pr in products:
            extra = " · ".join(filter(None, [pr.razmer, pr.rang, pr.qism]))
            pid = str(pr.id)
            miq = float(pr.miqdor or 0)
            p.append('<div class="op-card" id="inv-' + pid + '">')
            p.append('<div class="op-top"><div><div class="op-name">' + h(pr.name) + '</div>')
            if extra:
                p.append('<div class="op-extra">' + h(extra) + '</div>')
            p.append('</div><div class="op-qty">Bot: <b id="invbot-' + pid + '">' + ("%.0f" % miq) + '</b> <span>' + h(pr.birlik or "dona") + '</span></div></div>')
            p.append('<div class="op-ctrl">'
                     '<input type="number" id="invact-' + pid + '" placeholder="Haqiqiy son" class="op-amt" step="any" min="0">'
                     '<button class="op-b op-in-btn" onclick="doInv(' + pid + ')">✓ Saqlash</button>'
                     '</div><div class="inv-diff" id="invdiff-' + pid + '"></div></div>')
    p.append(_INV_JS)
    return web.Response(text=_base_ombor("Inventarizatsiya", "more", "\n".join(p), name), content_type="text/html")


@_require_role("omborchi")
async def ombor_inventar_post(request: web.Request):
    sess = _current(request)
    try:
        data = await request.json()
        pid = int(data.get("product_id"))
        haqiqiy = float(data.get("haqiqiy"))
    except (ValueError, TypeError):
        return web.json_response({"ok": False, "error": "Noto'g'ri ma'lumot"})
    if haqiqiy < 0:
        return web.json_response({"ok": False, "error": "Manfiy bo'lmasin"})
    async with AsyncSessionLocal() as db:
        pr = await db.get(WarehouseProduct, pid)
        if not pr:
            return web.json_response({"ok": False, "error": "Topilmadi"})
        bot_miq = float(pr.miqdor or 0)
        farq = haqiqiy - bot_miq
        if farq == 0:
            return web.json_response({"ok": True, "new_miqdor": bot_miq, "farq": 0})
        try:
            updated = await update_product_miqdor(
                db, pid, farq, sess.get("user_id"),
                izoh=f"Inventarizatsiya: bot={bot_miq:.0f} → haqiqiy={haqiqiy:.0f} (farq={farq:+.0f})",
            )
            await db.commit()
            return web.json_response({"ok": True, "new_miqdor": float(updated.miqdor), "farq": farq})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)[:100]})


# ─── 10. TRANSFER (zanjir — bir bo'limdan boshqasiga) ─────────────────────
@_require_role("omborchi")
async def ombor_transfer(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    msg = request.query.get("msg", "")
    async with AsyncSessionLocal() as db:
        products = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True, WarehouseProduct.miqdor > 0
            ).order_by(WarehouseProduct.name.asc())
        )).scalars().all()

    src_opts = ""
    for pr in products:
        extra = (" (" + h(pr.razmer) + ")") if pr.razmer else ""
        src_opts += ('<option value="' + str(pr.id) + '">' + h(pr.name) + extra +
                     ' — ' + ("%.0f" % float(pr.miqdor or 0)) + ' ' + h(pr.birlik or "dona") + '</option>')
    dst_opts = "".join('<option value="' + ck + '">' + cfg.get("title", ck) + '</option>' for ck, cfg in _CAT_CFG.items())
    import json as _json
    turlar_js = _json.dumps({ck: cfg.get("turlar", {}) for ck, cfg in _CAT_CFG.items()}, ensure_ascii=False)

    p = ['<h1>🔄 Transfer (zanjir)</h1>',
         '<p class="muted">Mahsulotni bir bo\'limdan boshqasiga (kerakli turga) ko\'chirish</p>']
    if msg == "ok":
        p.append('<div class="ok-msg">✅ Transfer amalga oshirildi!</div>')
    elif msg == "err":
        p.append('<div class="ok-msg" style="background:rgba(239,68,68,0.12);color:#f87171">⚠️ Xato: miqdor yetarli emas yoki mahsulot topilmadi</div>')
    p.append('<form method="post" action="/web/ombor-panel/transfer" class="add-form">')
    p.append('<label>Manba mahsulot (qayerdan)</label><select name="src_id" class="fld" required>' + src_opts + '</select>')
    p.append('<label>Maqsad bo\'lim (qayerga)</label>'
             '<select name="dst_cat" id="dcat" class="fld" onchange="updDTur()" required>' + dst_opts + '</select>')
    p.append('<label>Maqsad tur (masalan: yopishtirma uchun)</label><select name="dst_tur" id="dtur" class="fld"></select>')
    p.append('<label>Miqdor</label><input name="miqdor" type="number" step="any" min="0" class="fld" required>')
    p.append('<button class="save-btn">🔄 Ko\'chirish</button></form>')
    p.append('<script>var DTUR=' + turlar_js + ';'
             'function updDTur(){var c=document.getElementById("dcat").value;'
             'var sel=document.getElementById("dtur");var ts=DTUR[c]||{};'
             'sel.innerHTML="<option value=\\"\\">— tur tanlanmagan —</option>";'
             'for(var k in ts){var o=document.createElement("option");o.value=k;o.textContent=ts[k];sel.appendChild(o);}}'
             'updDTur();</script>')
    p.append(_ADD_CSS)
    return web.Response(text=_base_ombor("Transfer", "more", "\n".join(p), name), content_type="text/html")


@_require_role("omborchi")
async def ombor_transfer_post(request: web.Request):
    sess = _current(request)
    data = await request.post()
    try:
        src_id = int(data.get("src_id"))
        dst_cat = ProductCategory(data.get("dst_cat"))
        miqdor = float(data.get("miqdor") or 0)
    except (ValueError, TypeError):
        raise web.HTTPFound("/web/ombor-panel/transfer?msg=err")
    if miqdor <= 0:
        raise web.HTTPFound("/web/ombor-panel/transfer?msg=err")
    dst_tur = (data.get("dst_tur") or "").strip() or None

    async with AsyncSessionLocal() as db:
        src = await db.get(WarehouseProduct, src_id)
        if not src or float(src.miqdor or 0) < miqdor:
            raise web.HTTPFound("/web/ombor-panel/transfer?msg=err")
        uid = sess.get("user_id")
        # Manbadan ayirish
        await update_product_miqdor(db, src_id, -miqdor, uid,
                                    izoh=f"Transfer → {dst_cat.value}" + (f"/{dst_tur}" if dst_tur else ""))
        # Maqsadga qo'shish (mos mahsulot topib yoki yangi yaratib) — tur ham mos kelishi kerak
        dst = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True,
                WarehouseProduct.category == dst_cat,
                WarehouseProduct.name == src.name,
                WarehouseProduct.razmer == src.razmer,
                WarehouseProduct.rang == src.rang,
                WarehouseProduct.tur == dst_tur,
            ).limit(1)
        )).scalar_one_or_none()
        if dst:
            await update_product_miqdor(db, dst.id, miqdor, uid,
                                        izoh=f"Transfer ← {src.category.value if src.category else '?'}")
        else:
            new_p = WarehouseProduct(
                category=dst_cat, name=src.name, razmer=src.razmer, rang=src.rang,
                tur=dst_tur, qism=src.qism, birlik=src.birlik, miqdor=miqdor,
                min_threshold=src.min_threshold, yellow_threshold=src.yellow_threshold,
                qalinlik=getattr(src, "qalinlik", None), is_active=True,
            )
            db.add(new_p)
            await db.flush()
            db.add(WarehouseLog(product_id=new_p.id, user_id=uid, amal="kirim",
                                miqdor=miqdor, oldin=0.0, keyin=miqdor,
                                izoh=f"Transfer ← {src.category.value if src.category else '?'}"))
        await db.commit()
    raise web.HTTPFound("/web/ombor-panel/transfer?msg=ok")


# ─── 11. BUYURTMA RO'YXATI (kam qolgan mahsulotlar) ──────────────────────
@_require_role("omborchi")
async def ombor_buyurtma(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    async with AsyncSessionLocal() as db:
        products = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True,
                WarehouseProduct.miqdor <= WarehouseProduct.yellow_threshold,
            ).order_by(WarehouseProduct.miqdor.asc())
        )).scalars().all()

    kritik = [pr for pr in products if float(pr.miqdor or 0) <= float(pr.min_threshold or 0)]
    ogoh = [pr for pr in products if pr not in kritik]

    p = ['<h1>📋 Buyurtma ro\'yxati</h1>',
         '<p class="muted">Kam qolgan va tugagan mahsulotlar</p>']
    if not products:
        p.append('<div class="all-clear" style="background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);'
                 'border-radius:16px;padding:24px;text-align:center;color:#34d399;font-weight:700">'
                 '✅ Ombor holati yaxshi! Hamma mahsulot yetarli.</div>')
    else:
        if kritik:
            p.append('<div class="card"><div class="card-head"><h2 style="color:#f87171">🔴 Tugay deyapti</h2>'
                     '<span class="badge" style="background:#ef4444">' + str(len(kritik)) + '</span></div>')
            for pr in kritik:
                extra = " · ".join(filter(None, [pr.razmer, pr.rang, pr.qism]))
                sub = (CAT_LABELS.get(pr.category.value if pr.category else "", "") + (" · " + h(extra) if extra else ""))
                p.append('<div class="row"><div style="flex:1"><div class="row-name">' + h(pr.name) + '</div>'
                         '<div class="row-sub">' + sub + ' · min: ' + ("%.0f" % float(pr.min_threshold or 0)) + '</div></div>'
                         '<div class="row-qty" style="color:#f87171">' + ("%.0f" % float(pr.miqdor or 0)) + ' <span>' + h(pr.birlik or "dona") + '</span></div></div>')
            p.append('</div>')
        if ogoh:
            p.append('<div class="card"><div class="card-head"><h2 style="color:#fbbf24">🟡 Ogohlantirish</h2>'
                     '<span class="badge">' + str(len(ogoh)) + '</span></div>')
            for pr in ogoh:
                extra = " · ".join(filter(None, [pr.razmer, pr.rang, pr.qism]))
                sub = (CAT_LABELS.get(pr.category.value if pr.category else "", "") + (" · " + h(extra) if extra else ""))
                p.append('<div class="row"><div style="flex:1"><div class="row-name">' + h(pr.name) + '</div>'
                         '<div class="row-sub">' + sub + '</div></div>'
                         '<div class="row-qty warn">' + ("%.0f" % float(pr.miqdor or 0)) + ' <span>' + h(pr.birlik or "dona") + '</span></div></div>')
            p.append('</div>')
    return web.Response(text=_base_ombor("Buyurtma", "more", "\n".join(p), name), content_type="text/html")


_INV_JS = (
    '<script>'
    'function doInv(pid){'
    'var inp=document.getElementById("invact-"+pid);'
    'var val=parseFloat(inp.value);'
    'if(isNaN(val)||val<0){alert("Haqiqiy sonni kiriting");inp.focus();return;}'
    'var btn=event.target;'
    'fetch("/web/ombor-panel/inventar",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({product_id:pid,haqiqiy:val})})'
    '.then(function(r){return r.json();}).then(function(d){'
    'if(d.ok){document.getElementById("invbot-"+pid).textContent=Math.round(d.new_miqdor);'
    'var df=document.getElementById("invdiff-"+pid);'
    'var f=d.farq;df.textContent=f===0?"✓ Mos keldi":("Farq: "+(f>0?"+":"")+Math.round(f));'
    'df.style.color=f===0?"#34d399":(f>0?"#60a5fa":"#fbbf24");'
    'inp.value="";btn.textContent="✓ Saqlandi";'
    'setTimeout(function(){btn.textContent="✓ Saqlash";},1200);'
    '}else{alert("Xato: "+(d.error||"?"));}'
    '}).catch(function(e){alert("Tarmoq xatosi");});}'
    '</script>'
)


# ─── Route'larni ro'yxatga olish ─────────────────────────────────────────
def register_ombor_routes(app: web.Application):
    app.router.add_get("/web/ombor-panel", ombor_home)
    app.router.add_get("/web/ombor-panel/operatsiya", ombor_operatsiya)
    app.router.add_get("/web/ombor-panel/bolimlar", ombor_bolimlar)
    app.router.add_get("/web/ombor-panel/bolim/{cat}", ombor_bolim)
    app.router.add_get("/web/ombor-panel/hisobot", ombor_hisobot)
    app.router.add_get("/web/ombor-panel/tarix", ombor_tarix)
    app.router.add_get("/web/ombor-panel/qoshish", ombor_qoshish)
    app.router.add_post("/web/ombor-panel/qoshish", ombor_qoshish_post)
    app.router.add_get("/web/ombor-panel/tahrir/{id}", ombor_tahrir)
    app.router.add_post("/web/ombor-panel/tahrir/{id}", ombor_tahrir_post)
    app.router.add_get("/web/ombor-panel/ochirish/{id}", ombor_ochirish)
    app.router.add_get("/web/ombor-panel/inventar", ombor_inventar)
    app.router.add_post("/web/ombor-panel/inventar", ombor_inventar_post)
    app.router.add_get("/web/ombor-panel/transfer", ombor_transfer)
    app.router.add_post("/web/ombor-panel/transfer", ombor_transfer_post)
    app.router.add_get("/web/ombor-panel/buyurtma", ombor_buyurtma)
