"""
web_panel_inspektor.py — NAZORATCHI uchun alohida, mustaqil Web panel.
Faqat tekshirish/sifat bilan bog'liq funksiyalar. Admin sahifalariga havola yo'q.
Mobil-birinchi dizayn, pastki navigatsiya paneli bilan.
"""
from datetime import date, datetime, timedelta
from aiohttp import web
from sqlalchemy import select, func
import sqlalchemy.sql.functions as sf
from sqlalchemy import case as sa_case

from database.db import AsyncSessionLocal
from database.models import (
    WorkEntry, WorkStatus, User, QualityGrade,
)

from web_panel import _current, _require_role, h


# ─── Asosiy shablon (mustaqil) ───────────────────────────────────────────
def _base_insp(title: str, active: str, content: str, name: str = "Nazoratchi") -> str:
    nav = [
        ("home", "🏠", "Bosh", "/web/inspektor-panel"),
        ("review", "🔍", "Tekshirish", "/web/inspektor-panel/review"),
        ("quick", "⚡", "Tezkor", "/web/inspektor-panel/pending"),
        ("quality", "📊", "Sifat", "/web/inspektor-panel/sifat"),
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
        '<title>' + h(title) + ' — Nazorat</title>'
        + _INSP_CSS +
        '</head><body>'
        '<header class="top-bar">'
        '<div class="tb-left"><span class="tb-logo">✅</span><div>'
        '<div class="tb-title">Nazorat paneli</div>'
        '<div class="tb-sub">' + h(name) + '</div></div></div>'
        '<a href="/web/logout" class="tb-logout">Chiqish</a>'
        '</header>'
        '<main class="content">' + content + '</main>'
        '<nav class="bottom-nav">' + nav_html + '</nav>'
        '</body></html>'
    )


# ─── 1. BOSH SAHIFA ──────────────────────────────────────────────────────
@_require_role("nazoratchi")
async def insp_home(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Nazoratchi")
    uid = sess.get("user_id")
    today = date.today()
    week_ago = today - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        pending_n = int((await db.execute(
            select(func.count(WorkEntry.id)).where(WorkEntry.status == WorkStatus.pending)
        )).scalar() or 0)

        t = (await db.execute(
            select(
                sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
                sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
            ).where(WorkEntry.inspector_id == uid, func.date(WorkEntry.finished_at) == today)
        )).one()
        t_ok, t_rej = int(t[0] or 0), int(t[1] or 0)

        w = (await db.execute(
            select(
                func.count(WorkEntry.id),
                sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
            ).where(WorkEntry.work_date >= week_ago,
                    WorkEntry.status.in_([WorkStatus.approved, WorkStatus.rejected]))
        )).one()
        w_total, w_rej = int(w[0] or 0), int(w[1] or 0)
        qa = ((w_total - w_rej) / w_total * 100) if w_total else 100

        groups = (await db.execute(
            select(User.full_name, func.count(WorkEntry.id),
                   func.coalesce(func.sum(WorkEntry.jami_summa), 0))
            .join(WorkEntry, WorkEntry.worker_id == User.id)
            .where(WorkEntry.status == WorkStatus.pending)
            .group_by(User.id, User.full_name)
            .order_by(func.count(WorkEntry.id).desc()).limit(10)
        )).all()
        pend = [(r[0], int(r[1]), float(r[2])) for r in groups]

    p = []
    p.append('<div class="hero"><div><div class="hero-greet">Assalomu alaykum,</div>'
             '<div class="hero-name">' + h(name) + '</div>'
             '<div class="hero-date">' + today.strftime("%d.%m.%Y") + '</div></div>'
             '<div class="hero-emoji">✅</div></div>')

    if pending_n > 0:
        p.append('<a href="/web/inspektor-panel/review" class="banner">'
                 '<div><div class="banner-num">' + str(pending_n) + '</div>'
                 '<div class="banner-lbl">ish tekshirilishi kerak</div></div>'
                 '<div class="banner-arrow">Tekshirish →</div></a>')
    else:
        p.append('<div class="all-clear">🎉 Hamma ish tekshirilgan!</div>')

    p.append('<div class="kpi-grid">')
    p.append('<div class="kpi"><div class="kpi-num kpi-orange">' + str(pending_n) + '</div><div class="kpi-lbl">Kutilmoqda</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-green">' + str(t_ok) + '</div><div class="kpi-lbl">Bugun tasdiqladim</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-red">' + str(t_rej) + '</div><div class="kpi-lbl">Bugun rad etdim</div></div>')
    qc = "kpi-green" if qa >= 95 else ("kpi-orange" if qa >= 85 else "kpi-red")
    p.append('<div class="kpi"><div class="kpi-num ' + qc + '">' + ("%.0f" % qa) + '%</div><div class="kpi-lbl">Hafta sifati</div></div>')
    p.append('</div>')

    p.append('<div class="card"><div class="card-head"><h2>⏳ Kutilayotgan ishlar</h2>')
    if pending_n:
        p.append('<a href="/web/inspektor-panel/review" class="see-all">Tekshirish →</a>')
    p.append('</div>')
    if pend:
        for wn, cnt, summa in pend:
            ini = h(wn[0].upper()) if wn else "?"
            p.append('<div class="row"><div class="avatar">' + ini + '</div>'
                     '<div style="flex:1"><div class="row-name">' + h(wn) + '</div>'
                     '<div class="row-sub">' + str(cnt) + ' ta · ' + ("{:,.0f}".format(summa)) + ' so\'m</div></div>'
                     '<div class="pcount">' + str(cnt) + '</div></div>')
    else:
        p.append('<p class="empty">Kutilayotgan ish yo\'q</p>')
    p.append('</div>')

    return web.Response(text=_base_insp("Bosh", "home", "\n".join(p), name), content_type="text/html")


# ─── 2. BITTALAB TEKSHIRISH (sifat + rad etish) ──────────────────────────
@_require_role("nazoratchi")
async def insp_review(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Nazoratchi")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(WorkEntry, User).join(User, User.id == WorkEntry.worker_id)
            .where(WorkEntry.status == WorkStatus.pending)
            .order_by(WorkEntry.created_at.asc())
        )).all()

    p = ['<h1>Tekshirish</h1>', '<p class="muted">' + str(len(rows)) + ' ta ish — ishchi bo\'yicha guruhlangan</p>']
    if not rows:
        p.append('<div class="all-clear">🎉 Hamma ish tekshirilgan!</div>')
    else:
        # Ishchi bo'yicha guruhlash
        groups = {}
        for we, u in rows:
            groups.setdefault((u.id, u.full_name), []).append(we)

        for (uid, uname), items in groups.items():
            ini = h(uname[0].upper()) if uname else "?"
            total = sum(float(x.jami_summa or 0) for x in items)
            p.append('<div class="wgroup" id="wgroup-' + str(uid) + '">')
            # Ishchi sarlavhasi
            p.append('<div class="wg-head"><div class="avatar">' + ini + '</div>'
                     '<div style="flex:1"><div class="wg-name">' + h(uname) + '</div>'
                     '<div class="wg-sub">' + str(len(items)) + ' xil ish · ' + ("{:,.0f}".format(total)) + ' so\'m</div></div></div>')

            # Har bir ish — alohida karta
            for we in items:
                wt = (we.work_type.value if we.work_type else "?").replace("_", " ")
                wd = we.work_date.strftime("%d.%m") if we.work_date else ""
                wid = str(we.id)
                # Tafsilotlar (razmer, rang, tur, sloy, mahsulot nomi)
                details = []
                if we.mahsulot_nomi: details.append(h(we.mahsulot_nomi))
                if we.razmer: details.append("📐 " + h(we.razmer))
                if we.tur: details.append("🔖 " + h(we.tur))
                if we.sloy: details.append("📚 " + h(we.sloy) + "-sloy")
                if we.rang: details.append("🎨 " + h(we.rang))
                det_html = (" · ".join(details)) if details else ""

                p.append('<div class="wi" id="rev-' + wid + '">')
                p.append('<div class="wi-top"><div class="wi-type">' + h(wt) + '</div>'
                         '<div class="wi-num">' + ("%.0f" % we.soni) + ' dona</div></div>')
                if det_html:
                    p.append('<div class="wi-det">' + det_html + '</div>')
                p.append('<div class="wi-sum">💰 ' + ("{:,.0f}".format(we.jami_summa or 0)) + ' so\'m · 📅 ' + wd + '</div>')
                # Sifat
                p.append('<div class="rq">'
                         '<button class="rqb rqa on" onclick="setG(' + wid + ',1,this)">A·100%</button>'
                         '<button class="rqb rqbb" onclick="setG(' + wid + ',2,this)">B·80%</button>'
                         '<button class="rqb rqc" onclick="setG(' + wid + ',3,this)">C·60%</button></div>')
                # Amallar
                p.append('<div class="rev-act">'
                         '<button class="ok" onclick="appr(' + wid + ')">✅ Tasdiq</button>'
                         '<button class="no" onclick="showR(' + wid + ')">❌ Rad</button></div>')
                p.append('<div class="rej" id="rej-' + wid + '" style="display:none">'
                         '<div class="rej-lbl">Rad sababi:</div><div class="rej-btns">')
                for reason in ["Sifat past", "Miqdor xato", "Material xato", "Tugallanmagan", "Ikki marta", "Boshqa"]:
                    p.append('<button class="rejb" onclick="rej(' + wid + ',\'' + reason + '\')">' + reason + '</button>')
                p.append('</div></div>')

            # Ishchining hamma ishini A sifat bilan tasdiqlash
            p.append('<button class="wg-all" onclick="apprUser(' + str(uid) + ')">'
                     '✅ Bu ishchining hammasini tasdiqlash (' + str(len(items)) + ')</button>')
            p.append('</div>')
    p.append(_REVIEW_JS)
    return web.Response(text=_base_insp("Tekshirish", "review", "\n".join(p), name), content_type="text/html")


# ─── 3. TEZKOR TASDIQ (batch) ────────────────────────────────────────────
@_require_role("nazoratchi")
async def insp_pending(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Nazoratchi")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(WorkEntry, User).join(User, User.id == WorkEntry.worker_id)
            .where(WorkEntry.status == WorkStatus.pending)
            .order_by(WorkEntry.created_at.asc())
        )).all()

    p = ['<h1>Tezkor tasdiqlash</h1>', '<p class="muted">' + str(len(rows)) + ' ta ish — guruhlab tasdiqlash</p>']
    if not rows:
        p.append('<div class="all-clear">🎉 Hamma ish tekshirilgan!</div>')
    else:
        groups = {}
        for we, u in rows:
            groups.setdefault((u.id, u.full_name), []).append(we)
        for (uid, uname), items in groups.items():
            total = sum(float(x.jami_summa or 0) for x in items)
            p.append('<div class="card"><div class="card-head"><h2>👤 ' + h(uname) + '</h2>'
                     '<span class="badge">' + str(len(items)) + ' · ' + ("{:,.0f}".format(total)) + '</span></div>')
            for x in items:
                wt = (x.work_type.value if x.work_type else "?").replace("_", " ")
                wd = x.work_date.strftime("%d.%m") if x.work_date else ""
                dets = []
                if x.razmer: dets.append(h(x.razmer))
                if x.tur: dets.append(h(x.tur))
                if x.sloy: dets.append(h(x.sloy) + "-sloy")
                if x.rang: dets.append(h(x.rang))
                det = (" · " + " · ".join(dets)) if dets else ""
                p.append('<div class="wrow"><div class="wrow-t">' + h(wt) + det + '</div>'
                         '<div class="wrow-m">' + ("%.0f" % x.soni) + ' dona · ' + ("{:,.0f}".format(x.jami_summa or 0)) + ' so\'m · ' + wd + '</div></div>')
            p.append('<button class="appr-user" onclick="apprUser(' + str(uid) + ')">✅ Hammasini tasdiqlash (' + str(len(items)) + ')</button></div>')
        p.append('<button class="appr-all" onclick="apprAll()">✅✅ BARCHA ishlarni tasdiqlash</button>')
    p.append(_PENDING_JS)
    return web.Response(text=_base_insp("Tezkor", "quick", "\n".join(p), name), content_type="text/html")


# ─── 4. SIFAT HISOBOTI ───────────────────────────────────────────────────
@_require_role("nazoratchi")
async def insp_sifat(request: web.Request):
    sess = _current(request)
    name = sess.get("name", "Nazoratchi")
    today = date.today()
    month_ago = today - timedelta(days=30)
    async with AsyncSessionLocal() as db:
        stats = (await db.execute(
            select(
                func.count(WorkEntry.id),
                sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
                sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
            ).where(WorkEntry.work_date >= month_ago,
                    WorkEntry.status.in_([WorkStatus.approved, WorkStatus.rejected]))
        )).one()
        total, ok, rej = int(stats[0] or 0), int(stats[1] or 0), int(stats[2] or 0)
        qa = (ok / total * 100) if total else 100

        # Rad sabablari
        reasons = (await db.execute(
            select(WorkEntry.rad_sababi, func.count(WorkEntry.id))
            .where(WorkEntry.status == WorkStatus.rejected,
                   WorkEntry.work_date >= month_ago,
                   WorkEntry.rad_sababi.is_not(None))
            .group_by(WorkEntry.rad_sababi)
            .order_by(func.count(WorkEntry.id).desc())
        )).all()

        # Eng ko'p rad etilgan ishchilar
        worst = (await db.execute(
            select(User.full_name, func.count(WorkEntry.id))
            .join(WorkEntry, WorkEntry.worker_id == User.id)
            .where(WorkEntry.status == WorkStatus.rejected, WorkEntry.work_date >= month_ago)
            .group_by(User.id, User.full_name)
            .order_by(func.count(WorkEntry.id).desc()).limit(5)
        )).all()

    p = ['<h1>Sifat hisoboti</h1>', '<p class="muted">So\'nggi 30 kun</p>']
    p.append('<div class="kpi-grid">')
    p.append('<div class="kpi"><div class="kpi-num kpi-blue">' + str(total) + '</div><div class="kpi-lbl">Jami tekshirilgan</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-green">' + str(ok) + '</div><div class="kpi-lbl">Tasdiqlangan</div></div>')
    p.append('<div class="kpi"><div class="kpi-num kpi-red">' + str(rej) + '</div><div class="kpi-lbl">Rad etilgan</div></div>')
    qc = "kpi-green" if qa >= 95 else ("kpi-orange" if qa >= 85 else "kpi-red")
    p.append('<div class="kpi"><div class="kpi-num ' + qc + '">' + ("%.0f" % qa) + '%</div><div class="kpi-lbl">Sifat darajasi</div></div>')
    p.append('</div>')

    p.append('<div class="card"><div class="card-head"><h2>📋 Rad etish sabablari</h2></div>')
    if reasons:
        mx = max(int(r[1]) for r in reasons)
        for sab, cnt in reasons:
            cnt = int(cnt)
            pct = int(cnt / mx * 100) if mx else 0
            p.append('<div class="bar-row"><div class="bar-top"><span>' + h(sab or "?") + '</span><b>' + str(cnt) + '</b></div>'
                     '<div class="bar"><div class="bar-fill" style="width:' + str(pct) + '%"></div></div></div>')
    else:
        p.append('<p class="empty">Rad etilgan ish yo\'q 🎉</p>')
    p.append('</div>')

    p.append('<div class="card"><div class="card-head"><h2>⚠️ Eng ko\'p rad etilganlar</h2></div>')
    if worst:
        for wn, cnt in worst:
            ini = h(wn[0].upper()) if wn else "?"
            p.append('<div class="row"><div class="avatar">' + ini + '</div>'
                     '<div style="flex:1"><div class="row-name">' + h(wn) + '</div></div>'
                     '<div class="pcount red">' + str(int(cnt)) + '</div></div>')
    else:
        p.append('<p class="empty">Ma\'lumot yo\'q</p>')
    p.append('</div>')

    return web.Response(text=_base_insp("Sifat", "quality", "\n".join(p), name), content_type="text/html")


# ─── AMALLAR (API) ───────────────────────────────────────────────────────
@_require_role("nazoratchi")
async def insp_approve_one(request: web.Request):
    sess = _current(request)
    try:
        data = await request.json()
        wid = int(data.get("work_id", 0)); grade = int(data.get("grade", 1))
    except Exception:
        return web.json_response({"ok": False})
    gmap = {1: QualityGrade.grade_1, 2: QualityGrade.grade_2, 3: QualityGrade.grade_3}
    cmap = {1: 1.0, 2: 0.8, 3: 0.6}
    async with AsyncSessionLocal() as db:
        we = await db.get(WorkEntry, wid)
        if not we or we.status != WorkStatus.pending:
            return web.json_response({"ok": False, "error": "Topilmadi"})
        we.status = WorkStatus.approved
        we.inspector_id = sess.get("user_id")
        we.finished_at = datetime.now()
        we.quality_grade = gmap.get(grade, QualityGrade.grade_1)
        if grade > 1 and we.jami_summa:
            we.jami_summa = round(float(we.jami_summa) * cmap.get(grade, 1.0))
        await db.commit()
    return web.json_response({"ok": True})


@_require_role("nazoratchi")
async def insp_reject_one(request: web.Request):
    sess = _current(request)
    try:
        data = await request.json()
        wid = int(data.get("work_id", 0)); sabab = str(data.get("sabab", "Boshqa"))
    except Exception:
        return web.json_response({"ok": False})
    async with AsyncSessionLocal() as db:
        we = await db.get(WorkEntry, wid)
        if not we or we.status != WorkStatus.pending:
            return web.json_response({"ok": False, "error": "Topilmadi"})
        we.status = WorkStatus.rejected
        we.inspector_id = sess.get("user_id")
        we.finished_at = datetime.now()
        we.rad_sababi = sabab
        await db.commit()
    return web.json_response({"ok": True})


@_require_role("nazoratchi")
async def insp_approve_user(request: web.Request):
    sess = _current(request)
    try:
        data = await request.json(); wid = int(data.get("worker_id", 0))
    except Exception:
        return web.json_response({"ok": False})
    async with AsyncSessionLocal() as db:
        works = (await db.execute(select(WorkEntry).where(
            WorkEntry.status == WorkStatus.pending, WorkEntry.worker_id == wid))).scalars().all()
        now = datetime.now()
        for x in works:
            x.status = WorkStatus.approved; x.inspector_id = sess.get("user_id"); x.finished_at = now
        await db.commit()
    return web.json_response({"ok": True, "count": len(works)})


@_require_role("nazoratchi")
async def insp_approve_all(request: web.Request):
    sess = _current(request)
    async with AsyncSessionLocal() as db:
        works = (await db.execute(select(WorkEntry).where(
            WorkEntry.status == WorkStatus.pending))).scalars().all()
        now = datetime.now()
        for x in works:
            x.status = WorkStatus.approved; x.inspector_id = sess.get("user_id"); x.finished_at = now
        await db.commit()
    return web.json_response({"ok": True, "count": len(works)})


# ─── JS ──────────────────────────────────────────────────────────────────
_REVIEW_JS = (
    '<script>'
    'var G={};'
    'function setG(w,g,b){G[w]=g;var c=document.getElementById("rev-"+w);'
    'c.querySelectorAll(".rqb").forEach(function(x){x.classList.remove("on");});b.classList.add("on");}'
    'function fade(w,cls,txt){var c=document.getElementById("rev-"+w);c.classList.add(cls);'
    'c.innerHTML="<div class=\\"done\\">"+txt+"</div>";'
    'setTimeout(function(){c.remove();var l=document.querySelectorAll(".wi");'
    'if(l.length===0)location.reload();},700);}'
    'function appr(w){var g=G[w]||1;'
    'fetch("/web/inspektor/approve-one",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({work_id:w,grade:g})}).then(function(r){return r.json();}).then(function(d){'
    'if(d.ok){fade(w,"d-ok","✅ Tasdiqlandi");}else{alert("Xato");}});}'
    'function showR(w){var r=document.getElementById("rej-"+w);'
    'r.style.display=r.style.display==="none"?"block":"none";}'
    'function rej(w,s){if(!confirm("Rad etilsinmi? "+s))return;'
    'fetch("/web/inspektor/reject-one",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({work_id:w,sabab:s})}).then(function(r){return r.json();}).then(function(d){'
    'if(d.ok){fade(w,"d-no","❌ Rad etildi");}else{alert("Xato");}});}'
    'function apprUser(u){if(!confirm("Bu ishchining barcha ishlarini A sifat bilan tasdiqlaysizmi?"))return;'
    'fetch("/web/inspektor/approve-user",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({worker_id:u})}).then(function(r){return r.json();}).then(function(d){'
    'if(d.ok)location.reload();else alert("Xato");});}'
    '</script>'
)

_PENDING_JS = (
    '<script>'
    'function apprUser(u){if(!confirm("Bu ishchining barcha ishlarini tasdiqlaysizmi?"))return;'
    'fetch("/web/inspektor/approve-user",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({worker_id:u})}).then(function(r){return r.json();}).then(function(d){'
    'if(d.ok)location.reload();else alert("Xato");});}'
    'function apprAll(){if(!confirm("BARCHA kutilayotgan ishlarni tasdiqlaysizmi?"))return;'
    'fetch("/web/inspektor/approve-all",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})'
    '.then(function(r){return r.json();}).then(function(d){if(d.ok)location.reload();else alert("Xato");});}'
    '</script>'
)


# ─── CSS (mustaqil, mobil-birinchi) ──────────────────────────────────────
_INSP_CSS = """
<style>
* { box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent }
:root {
  --bg:#0f172a; --bg2:#1e293b; --fg:#f1f5f9; --muted:#94a3b8;
  --border:#334155; --accent:#10b981;
}
body { font-family:-apple-system,'Segoe UI',Roboto,sans-serif; background:var(--bg); color:var(--fg); padding-bottom:80px }
.top-bar { position:sticky; top:0; z-index:50; display:flex; justify-content:space-between; align-items:center;
  background:var(--bg2); border-bottom:1px solid var(--border); padding:12px 16px }
.tb-left { display:flex; align-items:center; gap:10px }
.tb-logo { font-size:26px }
.tb-title { font-weight:800; font-size:15px }
.tb-sub { font-size:12px; color:var(--muted) }
.tb-logout { color:#f87171; text-decoration:none; font-size:13px; font-weight:600;
  padding:6px 12px; border:1px solid rgba(248,113,113,0.3); border-radius:8px }
.content { padding:16px; max-width:760px; margin:0 auto }
h1 { font-size:22px; margin-bottom:4px }
.muted { color:var(--muted); font-size:14px; margin-bottom:16px }
.empty { text-align:center; color:var(--muted); padding:30px }

.hero { display:flex; justify-content:space-between; align-items:center;
  background:linear-gradient(135deg,#10b981,#059669); border-radius:18px; padding:22px; color:#fff; margin-bottom:18px }
.hero-greet { font-size:14px; opacity:0.9 }
.hero-name { font-size:22px; font-weight:800 }
.hero-date { font-size:13px; opacity:0.85; margin-top:2px }
.hero-emoji { font-size:46px }

.banner { display:flex; justify-content:space-between; align-items:center;
  background:linear-gradient(135deg,#f59e0b,#d97706); color:#fff; border-radius:16px; padding:20px;
  text-decoration:none; margin-bottom:18px; box-shadow:0 8px 24px rgba(245,158,11,0.3) }
.banner-num { font-size:36px; font-weight:800; line-height:1 }
.banner-lbl { font-size:14px; opacity:0.95 }
.banner-arrow { font-weight:700 }
.all-clear { text-align:center; padding:30px; background:rgba(16,185,129,0.1);
  border:1px solid rgba(16,185,129,0.3); border-radius:16px; font-size:18px; font-weight:700; color:#34d399; margin-bottom:18px }

.kpi-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; margin-bottom:16px }
.kpi { background:var(--bg2); border:1px solid var(--border); border-radius:16px; padding:18px; text-align:center }
.kpi-num { font-size:30px; font-weight:800; line-height:1 }
.kpi-lbl { font-size:12px; color:var(--muted); margin-top:6px; font-weight:600 }
.kpi-blue{color:#60a5fa} .kpi-orange{color:#fbbf24} .kpi-red{color:#f87171} .kpi-green{color:#34d399}

.card { background:var(--bg2); border:1px solid var(--border); border-radius:16px; padding:16px; margin-bottom:14px }
.card-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px }
.card-head h2 { font-size:16px }
.badge { background:#f59e0b; color:#fff; border-radius:20px; padding:2px 12px; font-size:12px; font-weight:700 }
.see-all { color:var(--accent); text-decoration:none; font-size:13px; font-weight:600 }

.row { display:flex; align-items:center; gap:12px; padding:10px 0; border-bottom:1px solid var(--border) }
.row:last-child { border-bottom:none }
.row-name { font-weight:600; font-size:14px }
.row-sub { font-size:12px; color:var(--muted); margin-top:2px }
.avatar { width:42px; height:42px; border-radius:50%; background:linear-gradient(135deg,#6366f1,#8b5cf6);
  color:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:17px }
.pcount { background:#f59e0b; color:#fff; border-radius:12px; min-width:34px; height:34px; padding:0 9px;
  display:flex; align-items:center; justify-content:center; font-weight:800 }
.pcount.red { background:#ef4444 }

.wrow { padding:9px 12px; background:var(--bg); border-radius:10px; border-left:3px solid var(--accent); margin-bottom:6px }
.wrow-t { font-weight:600; font-size:13px; text-transform:capitalize }
.wrow-m { font-size:11px; color:var(--muted); margin-top:2px }
.appr-user { width:100%; padding:12px; border:none; border-radius:12px; margin-top:6px;
  background:linear-gradient(135deg,#10b981,#059669); color:#fff; font-weight:700; font-size:14px; cursor:pointer }
.appr-all { width:100%; padding:16px; border:none; border-radius:14px; margin-top:8px;
  background:linear-gradient(135deg,#6366f1,#4f46e5); color:#fff; font-weight:800; font-size:16px; cursor:pointer;
  box-shadow:0 8px 24px rgba(99,102,241,0.3) }

.rev { background:var(--bg2); border:1px solid var(--border); border-radius:16px; padding:16px; margin-bottom:14px; transition:opacity .3s }
.rev.d-ok, .rev.d-no { opacity:0.5 }
.done { text-align:center; padding:18px; font-weight:700 }
.d-ok .done { color:#34d399 } .d-no .done { color:#f87171 }
.rev-head { display:flex; align-items:center; gap:12px; margin-bottom:12px }
.rev-wt { font-size:13px; color:var(--muted); text-transform:capitalize }
.rev-det { display:flex; gap:10px; margin-bottom:14px }
.rd { flex:1; background:var(--bg); border-radius:10px; padding:10px; text-align:center }
.rd span { display:block; font-size:11px; color:var(--muted); margin-bottom:3px }
.rd b { font-size:14px }
.rq-lbl { font-size:13px; color:var(--muted); margin-bottom:6px; font-weight:600 }
.rq { display:flex; gap:8px; margin-bottom:12px }
.rqb { flex:1; padding:11px 4px; border:2px solid var(--border); border-radius:10px; background:var(--bg);
  color:var(--fg); font-weight:700; font-size:12px; cursor:pointer }
.rqb.on.rqa { background:#10b981; color:#fff; border-color:#10b981 }
.rqb.on.rqbb { background:#f59e0b; color:#fff; border-color:#f59e0b }
.rqb.on.rqc { background:#ef4444; color:#fff; border-color:#ef4444 }
.rev-act { display:flex; gap:10px }
.ok { flex:2; padding:13px; border:none; border-radius:12px; background:linear-gradient(135deg,#10b981,#059669);
  color:#fff; font-weight:700; font-size:15px; cursor:pointer }
.no { flex:1; padding:13px; border:none; border-radius:12px; background:linear-gradient(135deg,#ef4444,#dc2626);
  color:#fff; font-weight:700; font-size:15px; cursor:pointer }
.rej { margin-top:12px; padding:12px; background:rgba(239,68,68,0.08); border-radius:12px; border:1px solid rgba(239,68,68,0.3) }
.rej-lbl { font-size:13px; font-weight:700; color:#f87171; margin-bottom:8px }
.rej-btns { display:flex; flex-wrap:wrap; gap:8px }
.rejb { padding:9px 13px; border:1px solid rgba(239,68,68,0.4); border-radius:20px; background:var(--bg);
  color:var(--fg); font-size:13px; font-weight:600; cursor:pointer }
.rejb:active { background:#ef4444; color:#fff }

.wgroup { background:var(--bg2); border:1px solid var(--border); border-radius:16px; padding:14px; margin-bottom:16px }
.wg-head { display:flex; align-items:center; gap:12px; padding-bottom:12px; margin-bottom:12px; border-bottom:2px solid var(--border) }
.wg-name { font-weight:800; font-size:16px }
.wg-sub { font-size:12px; color:var(--muted); margin-top:2px }
.wi { background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:12px; margin-bottom:10px; transition:opacity .3s }
.wi.d-ok, .wi.d-no { opacity:0.45 }
.wi-top { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px }
.wi-type { font-weight:700; font-size:14px; text-transform:capitalize }
.wi-num { font-weight:800; font-size:14px; color:#60a5fa }
.wi-det { font-size:12px; color:var(--muted); margin-bottom:6px; line-height:1.5 }
.wi-sum { font-size:12px; color:var(--muted); margin-bottom:10px }
.wg-all { width:100%; padding:13px; border:none; border-radius:12px; margin-top:4px;
  background:linear-gradient(135deg,#10b981,#059669); color:#fff; font-weight:700; font-size:14px; cursor:pointer }

.bar-row { margin-bottom:12px }
.bar-top { display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px }
.bar { height:8px; background:var(--bg); border-radius:6px; overflow:hidden }
.bar-fill { height:100%; background:linear-gradient(90deg,#ef4444,#f59e0b); border-radius:6px }

.bottom-nav { position:fixed; bottom:0; left:0; right:0; z-index:50; display:flex;
  background:var(--bg2); border-top:1px solid var(--border); padding:6px 0 calc(6px + env(safe-area-inset-bottom)) }
.bnav-item { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px;
  text-decoration:none; color:var(--muted); padding:6px 0; font-size:11px; font-weight:600 }
.bnav-icon { font-size:22px }
.nav-active { color:var(--accent) }

@media (min-width:760px) { .kpi-grid { grid-template-columns:repeat(4,1fr) } }
</style>
"""


# ─── Route'larni ro'yxatga olish ─────────────────────────────────────────
def register_inspektor_routes(app: web.Application):
    app.router.add_get("/web/inspektor-panel", insp_home)
    app.router.add_get("/web/inspektor-panel/review", insp_review)
    app.router.add_get("/web/inspektor-panel/pending", insp_pending)
    app.router.add_get("/web/inspektor-panel/sifat", insp_sifat)
    app.router.add_post("/web/inspektor/approve-one", insp_approve_one)
    app.router.add_post("/web/inspektor/reject-one", insp_reject_one)
    app.router.add_post("/web/inspektor/approve-user", insp_approve_user)
    app.router.add_post("/web/inspektor/approve-all", insp_approve_all)
