"""
web_panel_rulon.py — RULON ISHLAB CHIQARISH HISOBOTI (admin).
Kun / hafta / oy bo'yicha qancha rulon ishlab chiqarildi.
Bir xil rulonlar (razmer + gramaj + rang) bitta qatorda jamlangan.
"""
from datetime import date, datetime, timedelta
from aiohttp import web
from sqlalchemy import select, func

from database.db import AsyncSessionLocal
from database.models import WorkEntry, WorkStatus, WorkType, User

from web_panel import _base, _require_role, h


@_require_role("admin")
async def rulon_hisobot(request: web.Request):
    period = request.query.get("period", "week")  # today | week | month
    today = date.today()
    if period == "today":
        start = today
        plabel = "Bugun"
    elif period == "month":
        start = today.replace(day=1)
        plabel = "Bu oy"
    else:
        start = today - timedelta(days=7)
        plabel = "So'nggi 7 kun"

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(WorkEntry, User)
            .join(User, User.id == WorkEntry.worker_id)
            .where(
                WorkEntry.work_type == WorkType.rulon_ishlab,
                WorkEntry.work_date >= start,
            )
            .order_by(WorkEntry.work_date.desc())
        )).all()

    # Guruhlash: (mahsulot_nomi yoki razmer+rang) bo'yicha
    groups = {}
    total_count = 0.0
    total_sum = 0.0
    st_approved = st_pending = st_rejected = 0
    for we, u in rows:
        key = we.mahsulot_nomi or (str(we.razmer or "") + " " + str(we.rang or ""))
        g = groups.setdefault(key, {
            "razmer": we.razmer or "", "rang": we.rang or "",
            "nomi": we.mahsulot_nomi or key,
            "soni": 0.0, "summa": 0.0,
            "approved": 0, "pending": 0, "rejected": 0,
        })
        s = float(we.soni or 0)
        g["soni"] += s
        g["summa"] += float(we.jami_summa or 0)
        total_count += s
        total_sum += float(we.jami_summa or 0)
        stv = we.status.value if we.status else ""
        if stv == "approved":
            g["approved"] += 1; st_approved += 1
        elif stv == "rejected":
            g["rejected"] += 1; st_rejected += 1
        else:
            g["pending"] += 1; st_pending += 1

    glist = sorted(groups.values(), key=lambda x: x["soni"], reverse=True)

    p = []
    p.append('<h1>🌀 Rulon ishlab chiqarish hisoboti</h1>')
    p.append('<p style="color:var(--muted);margin-bottom:16px">' + plabel + '</p>')

    # Davr filtri
    p.append('<div class="rh-tabs">')
    for key, label in [("today", "Bugun"), ("week", "Hafta"), ("month", "Oy")]:
        on = "rh-tab-on" if period == key else ""
        p.append('<a href="/web/rulon-hisobot?period=' + key + '" class="rh-tab ' + on + '">' + label + '</a>')
    p.append('</div>')

    # Umumiy KPI
    p.append('<div class="rh-kpi">')
    p.append('<div class="rh-card"><div class="rh-num">' + ("%.0f" % total_count) + '</div><div class="rh-lbl">Jami rulon</div></div>')
    p.append('<div class="rh-card"><div class="rh-num rh-green">' + str(st_approved) + '</div><div class="rh-lbl">Tasdiqlangan</div></div>')
    p.append('<div class="rh-card"><div class="rh-num rh-orange">' + str(st_pending) + '</div><div class="rh-lbl">Kutilmoqda</div></div>')
    p.append('<div class="rh-card"><div class="rh-num rh-red">' + str(st_rejected) + '</div><div class="rh-lbl">Rad etilgan</div></div>')
    p.append('</div>')

    # Guruhlangan jadval — bir xil rulonlar bitta qatorda
    p.append('<div class="rh-table-wrap"><h2 style="margin:8px 0 12px">Turlari bo\'yicha</h2>')
    if not glist:
        p.append('<p style="text-align:center;color:var(--muted);padding:30px">Bu davrda rulon ishlab chiqarilmagan</p>')
    else:
        p.append('<table class="rh-table"><thead><tr>'
                 '<th>Rulon turi</th><th>Razmer</th><th>Rang</th>'
                 '<th>Soni</th><th>Holat</th></tr></thead><tbody>')
        for g in glist:
            status_html = ('<span class="st-ok">' + str(g["approved"]) + '✓</span> '
                           '<span class="st-pend">' + str(g["pending"]) + '⏳</span> '
                           '<span class="st-rej">' + str(g["rejected"]) + '✗</span>')
            p.append('<tr>'
                     '<td><b>' + h(g["nomi"]) + '</b></td>'
                     '<td>' + h(g["razmer"]) + '</td>'
                     '<td>' + h(g["rang"]) + '</td>'
                     '<td class="rh-cnt">' + ("%.0f" % g["soni"]) + '</td>'
                     '<td class="rh-st">' + status_html + '</td>'
                     '</tr>')
        p.append('</tbody></table>')
    p.append('</div>')

    p.append(_RULON_CSS)
    return web.Response(text=_base("Rulon hisobot", "rulon-hisobot", "\n".join(p)), content_type="text/html")


_RULON_CSS = """
<style>
.rh-tabs { display:flex; gap:8px; margin-bottom:16px }
.rh-tab { padding:9px 18px; border-radius:20px; background:var(--bg2); border:1px solid var(--border);
  color:var(--fg); text-decoration:none; font-size:14px; font-weight:600 }
.rh-tab-on { background:#6366f1; color:#fff; border-color:#6366f1 }
.rh-kpi { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:20px }
.rh-card { background:var(--bg2); border:1px solid var(--border); border-radius:14px; padding:16px; text-align:center }
.rh-num { font-size:28px; font-weight:800 }
.rh-green { color:#34d399 } .rh-orange { color:#fbbf24 } .rh-red { color:#f87171 }
.rh-lbl { font-size:12px; color:var(--muted); margin-top:5px; font-weight:600 }
.rh-table-wrap { background:var(--bg2); border:1px solid var(--border); border-radius:16px; padding:16px; overflow-x:auto }
.rh-table { width:100%; border-collapse:collapse; min-width:480px }
.rh-table th { text-align:left; font-size:12px; color:var(--muted); padding:8px 10px; border-bottom:2px solid var(--border) }
.rh-table td { padding:11px 10px; border-bottom:1px solid var(--border); font-size:14px }
.rh-cnt { font-weight:800; color:#60a5fa; font-size:16px }
.rh-st { white-space:nowrap }
.st-ok { color:#34d399; font-weight:700 } .st-pend { color:#fbbf24; font-weight:700 } .st-rej { color:#f87171; font-weight:700 }
@media (max-width:768px) { .rh-kpi { grid-template-columns:repeat(2,1fr) } }
</style>
"""


def register_rulon_routes(app: web.Application):
    app.router.add_get("/web/rulon-hisobot", rulon_hisobot)
