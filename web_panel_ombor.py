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

# Umumiy yordamchilar (web_panel.py dan)
from web_panel import _current, _require_role, h


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


# ─── 3. BO'LIMLAR ro'yxati ───────────────────────────────────────────────
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
        cats = [(r[0].value if r[0] else "?", int(r[1] or 0), int(r[2] or 0)) for r in cat_rows]

    p = ['<h1>Bo\'limlar</h1>',
         '<a href="/web/ombor-panel/qoshish" class="add-link">➕ Yangi mahsulot qo\'shish</a>',
         '<div class="cat-grid">']
    for ck, cnt, low in cats:
        warn = ('<span class="cat-warn">⚠️ ' + str(low) + '</span>') if low else ''
        p.append('<a href="/web/ombor-panel/bolim/' + ck + '" class="cat-tile">'
                 '<div class="cat-name">' + CAT_LABELS.get(ck, ck) + '</div>'
                 '<div class="cat-cnt">' + str(cnt) + ' <span>dona</span></div>' + warn + '</a>')
    p.append('</div>')
    return web.Response(text=_base_ombor("Bo'limlar", "cats", "\n".join(p), name), content_type="text/html")


# ─── 4. BITTA BO'LIM ichidagi mahsulotlar ────────────────────────────────
@_require_role("omborchi")
async def ombor_bolim(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Omborchi")
    ck = request.match_info.get("cat", "")
    try:
        cat_enum = ProductCategory(ck)
    except ValueError:
        return web.HTTPFound("/web/ombor-panel/bolimlar")

    async with AsyncSessionLocal() as db:
        products = (await db.execute(
            select(WarehouseProduct).where(
                WarehouseProduct.is_active == True, WarehouseProduct.category == cat_enum
            ).order_by(WarehouseProduct.name.asc())
        )).scalars().all()

    p = ['<h1>' + CAT_LABELS.get(ck, ck) + '</h1>',
         '<p class="muted">' + str(len(products)) + ' ta mahsulot</p>']
    if not products:
        p.append('<p class="empty">Bo\'lim bo\'sh</p>')
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
            p.append('</div><a href="/web/ombor-panel/tahrir/' + pid + '" class="edit-link">✏️</a>'
                     '<div class="op-qty" style="color:' + color + '">'
                     + ("%.0f" % miq) + ' <span>' + h(pr.birlik or "dona") + '</span></div></div>')
            p.append('<div class="op-ctrl">'
                     '<input type="number" id="amt-' + pid + '" placeholder="Miqdor" class="op-amt" step="any" min="0">'
                     '<button class="op-b op-in-btn" onclick="doOp(' + pid + ',1)">+ Kirim</button>'
                     '<button class="op-b op-out-btn" onclick="doOp(' + pid + ',-1)">− Chiqim</button>'
                     '</div></div>')
    p.append(_OPS_JS)
    return web.Response(text=_base_ombor(CAT_LABELS.get(ck, ck), "cats", "\n".join(p), name), content_type="text/html")


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

    cat_options = ""
    for ck, label in CAT_LABELS.items():
        cat_options += '<option value="' + ck + '">' + label + '</option>'

    p = ['<h1>Yangi mahsulot</h1>', '<p class="muted">Omborga yangi mahsulot qo\'shish</p>']
    if msg == "ok":
        p.append('<div class="ok-msg">✅ Mahsulot qo\'shildi!</div>')

    p.append('<form method="post" action="/web/ombor-panel/qoshish" class="add-form">')
    p.append('<label>Bo\'lim (kategoriya)</label>'
             '<select name="category" class="fld" required>' + cat_options + '</select>')
    p.append('<label>Nomi *</label><input name="name" class="fld" placeholder="Masalan: Oq rulon 120sm" required>')
    p.append('<div class="frow">'
             '<div><label>Razmer</label><input name="razmer" class="fld" placeholder="120sm"></div>'
             '<div><label>Rang</label><input name="rang" class="fld" placeholder="oq"></div></div>')
    p.append('<div class="frow">'
             '<div><label>Birlik</label><input name="birlik" class="fld" value="dona"></div>'
             '<div><label>Boshlang\'ich miqdor</label><input name="miqdor" type="number" step="any" class="fld" value="0"></div></div>')
    p.append('<div class="frow">'
             '<div><label>Kam chegarasi (qizil)</label><input name="min_threshold" type="number" step="any" class="fld" value="10"></div>'
             '<div><label>Ogoh chegarasi (sariq)</label><input name="yellow_threshold" type="number" step="any" class="fld" value="20"></div></div>')
    p.append('<button class="save-btn">💾 Qo\'shish</button></form>')

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

    async with AsyncSessionLocal() as db:
        db.add(WarehouseProduct(
            category=cat,
            name=name_v,
            razmer=(data.get("razmer") or "").strip() or None,
            rang=(data.get("rang") or "").strip() or None,
            birlik=(data.get("birlik") or "dona").strip(),
            miqdor=_f("miqdor", 0),
            min_threshold=_f("min_threshold", 10),
            yellow_threshold=_f("yellow_threshold", 20),
            is_active=True,
        ))
        await db.commit()
    raise web.HTTPFound("/web/ombor-panel/qoshish?msg=ok")


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
.save-btn { margin-top:16px; padding:15px; border:none; border-radius:12px; background:linear-gradient(135deg,#10b981,#059669); color:#fff; font-weight:800; font-size:16px; cursor:pointer }
.del-btn { display:block; text-align:center; margin-top:12px; padding:14px; border-radius:12px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.4); color:#f87171; text-decoration:none; font-weight:700 }
.ok-msg { background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.4); color:#34d399; padding:14px; border-radius:12px; font-weight:700; text-align:center; margin-bottom:16px }
</style>
"""


# ─── Route'larni ro'yxatga olish ─────────────────────────────────────────
def register_ombor_routes(app: web.Application):
    app.router.add_get("/web/ombor-panel", ombor_home)
    app.router.add_get("/web/ombor-panel/operatsiya", ombor_operatsiya)
    app.router.add_get("/web/ombor-panel/bolimlar", ombor_bolimlar)
    app.router.add_get("/web/ombor-panel/bolim/{cat}", ombor_bolim)
    app.router.add_get("/web/ombor-panel/tarix", ombor_tarix)
    app.router.add_get("/web/ombor-panel/qoshish", ombor_qoshish)
    app.router.add_post("/web/ombor-panel/qoshish", ombor_qoshish_post)
    app.router.add_get("/web/ombor-panel/tahrir/{id}", ombor_tahrir)
    app.router.add_post("/web/ombor-panel/tahrir/{id}", ombor_tahrir_post)
    app.router.add_get("/web/ombor-panel/ochirish/{id}", ombor_ochirish)
