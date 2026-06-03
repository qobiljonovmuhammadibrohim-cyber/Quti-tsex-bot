"""
web_panel_topshiriq.py — ADMIN uchun topshiriq (vazifa) boshqaruvi.
Admin ishchiga topshiriq beradi: qaysi ish, qancha, razmer, qaysi material.
Material yetarliligini tekshiradi.
"""
import json
from datetime import date, datetime
from aiohttp import web
from sqlalchemy import select, func

from database.db import AsyncSessionLocal
from database.models import (
    Topshiriq, TopshiriqStatus, User, UserRole, WorkType,
    WarehouseProduct,
)
from constants import get_variants, get_work_name, PRICE_VARIANTS

from web_panel import _base, _require_role, _current, h


# ─── 1. TOPSHIRIQLAR RO'YXATI ────────────────────────────────────────────
@_require_role("admin")
async def topshiriqlar(request: web.Request):
    flt = request.query.get("status", "faol")
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(Topshiriq, User)
                .join(User, User.id == Topshiriq.worker_id)
                .order_by(Topshiriq.created_at.desc())
            )
            if flt == "faol":
                stmt = stmt.where(Topshiriq.status.in_([TopshiriqStatus.tayinlangan, TopshiriqStatus.qisman]))
            elif flt == "qisman":
                stmt = stmt.where(Topshiriq.status == TopshiriqStatus.qisman)
            elif flt == "yakunlangan":
                stmt = stmt.where(Topshiriq.status.in_([TopshiriqStatus.bajarilgan, TopshiriqStatus.yakunlangan]))
            rows = (await db.execute(stmt.limit(100))).all()

            cnt_active = int((await db.execute(
                select(func.count(Topshiriq.id)).where(
                    Topshiriq.status.in_([TopshiriqStatus.tayinlangan, TopshiriqStatus.qisman]))
            )).scalar() or 0)
            cnt_partial = int((await db.execute(
                select(func.count(Topshiriq.id)).where(Topshiriq.status == TopshiriqStatus.qisman)
            )).scalar() or 0)
    except Exception as e:
        content = (
            '<h1>📋 Topshiriqlar</h1>'
            '<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.4);'
            'border-radius:12px;padding:20px;margin-top:16px">'
            '<b style="color:#f87171">⚠️ Topshiriqlar jadvali hali bazada yaratilmagan.</b>'
            '<p style="color:var(--muted);margin-top:10px">Railway\'da quyidagini bajaring:<br>'
            '1. Deployments → oxirgi deploy tugaganini tekshiring<br>'
            '2. Agar kerak bo\'lsa qayta deploy qiling (migrate.py jadvalni yaratadi)<br>'
            '3. Yoki menga xabar bering — qo\'lda yarataylik</p>'
            '<p style="color:var(--muted);font-size:12px;margin-top:8px">Texnik: ' + h(str(e)[:120]) + '</p>'
            '</div>'
        )
        return web.Response(text=_base("Topshiriqlar", "topshiriqlar", content), content_type="text/html")

    STATUS_BADGE = {
        "tayinlangan": ("Tayinlangan", "#3b82f6"),
        "qisman":      ("Qisman ⚠️", "#f59e0b"),
        "bajarilgan":  ("Bajarilgan", "#10b981"),
        "yakunlangan": ("Yakunlangan", "#64748b"),
        "bekor":       ("Bekor", "#ef4444"),
    }

    p = []
    p.append('<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">')
    p.append('<h1 style="margin:0">📋 Topshiriqlar</h1>')
    p.append('<a href="/web/topshiriqlar/yangi" class="t-new-btn">➕ Yangi topshiriq</a>')
    p.append('</div>')
    p.append('<p style="color:var(--muted);margin-bottom:16px">Faol: ' + str(cnt_active) +
             ' · Qaror kutmoqda: ' + str(cnt_partial) + '</p>')

    # Filtr
    p.append('<div class="t-tabs">')
    for key, label in [("faol", "Faol"), ("qisman", "Qaror kutmoqda"), ("yakunlangan", "Yakunlangan"), ("all", "Barchasi")]:
        on = "t-tab-on" if flt == key else ""
        p.append('<a href="/web/topshiriqlar?status=' + key + '" class="t-tab ' + on + '">' + label + '</a>')
    p.append('</div>')

    if not rows:
        p.append('<p style="text-align:center;color:var(--muted);padding:40px">Topshiriq yo\'q</p>')
    else:
        for tp, u in rows:
            wt = get_work_name(tp.work_type.value if tp.work_type else "?")
            label, color = STATUS_BADGE.get(tp.status.value, (tp.status.value, "#64748b"))
            target = float(tp.target_soni or 0)
            done = float(tp.done_soni or 0)
            pct = int(done / target * 100) if target else 0
            variant = (" · " + h(tp.razmer_turi)) if tp.razmer_turi else ""
            dl = ("📅 " + tp.deadline.strftime("%d.%m.%Y")) if tp.deadline else ""

            p.append('<div class="t-card">')
            p.append('<div class="t-card-head">')
            p.append('<div><div class="t-worker">👷 ' + h(u.full_name) + '</div>'
                     '<div class="t-work">' + wt + variant + '</div></div>')
            p.append('<span class="t-badge" style="background:' + color + '">' + label + '</span>')
            p.append('</div>')
            # Progress
            p.append('<div class="t-prog-row"><span>' + ("%.0f" % done) + ' / ' + ("%.0f" % target) +
                     ' dona</span><span>' + dl + '</span></div>')
            p.append('<div class="t-prog"><div class="t-prog-fill" style="width:' + str(min(pct, 100)) + '%"></div></div>')
            # Qisman bo'lsa — admin qarori
            if tp.status == TopshiriqStatus.qisman:
                rem = target - done
                p.append('<div class="t-decide"><div class="t-decide-lbl">Qolgan ' + ("%.0f" % rem) +
                         ' dona uchun qaror:</div><div class="t-decide-btns">')
                p.append('<button class="t-db t-close" onclick="decide(' + str(tp.id) + ',\'close\')">Yopish (' + ("%.0f" % done) + ' qabul)</button>')
                p.append('<button class="t-db t-keep" onclick="decide(' + str(tp.id) + ',\'keep\')">Davom (qolgan ' + ("%.0f" % rem) + ')</button>')
                p.append('</div></div>')
            p.append('</div>')

    p.append(_TASK_LIST_JS)
    p.append(_TASK_CSS)
    return web.Response(text=_base("Topshiriqlar", "topshiriqlar", "\n".join(p)), content_type="text/html")


# ─── 2. YANGI TOPSHIRIQ ──────────────────────────────────────────────────
@_require_role("admin")
async def topshiriq_yangi(request: web.Request):
    async with AsyncSessionLocal() as db:
        workers = (await db.execute(
            select(User).where(User.role == UserRole.ishchi, User.is_active == True)
            .order_by(User.full_name.asc())
        )).scalars().all()
        products = (await db.execute(
            select(WarehouseProduct).where(WarehouseProduct.is_active == True)
            .order_by(WarehouseProduct.name.asc())
        )).scalars().all()

    # JS uchun ma'lumotlar
    variants_js = json.dumps(PRICE_VARIANTS, ensure_ascii=False)
    prod_js = json.dumps(
        {str(pr.id): {"name": pr.name, "miqdor": float(pr.miqdor or 0), "birlik": pr.birlik or "dona"}
         for pr in products}, ensure_ascii=False
    )

    worker_opts = "".join('<option value="' + str(w.id) + '">' + h(w.full_name) + '</option>' for w in workers)
    wt_opts = "".join('<option value="' + wt.value + '">' + get_work_name(wt.value) + '</option>' for wt in WorkType)
    prod_opts = '<option value="">— material tanlanmagan —</option>'
    for pr in products:
        extra = (" (" + h(pr.razmer) + ")") if pr.razmer else ""
        prod_opts += ('<option value="' + str(pr.id) + '">' + h(pr.name) + extra +
                      ' — ' + ("%.0f" % float(pr.miqdor or 0)) + ' ' + h(pr.birlik or "dona") + '</option>')

    p = []
    p.append('<h1>➕ Yangi topshiriq</h1>')
    p.append('<p style="color:var(--muted);margin-bottom:16px">Ishchiga vazifa bering</p>')
    p.append('<form method="post" action="/web/topshiriqlar/yangi" class="t-form">')
    p.append('<label>Ishchi *</label><select name="worker_id" class="t-fld" required>' + worker_opts + '</select>')
    p.append('<label>Ish turi *</label><select name="work_type" id="wt" class="t-fld" onchange="updVariants()" required>' + wt_opts + '</select>')
    p.append('<label>Razmer / variant</label><select name="razmer_turi" id="variant" class="t-fld"></select>')
    p.append('<label>Reja miqdori (nechta) *</label><input name="target_soni" id="target" type="number" step="any" min="1" class="t-fld" oninput="checkMat()" required>')
    p.append('<label>Material (ombor mahsuloti)</label><select name="product_id" id="prod" class="t-fld" onchange="checkMat()">' + prod_opts + '</select>')
    p.append('<div id="mat-check" class="mat-check"></div>')
    p.append('<label>Muddat (ixtiyoriy)</label><input name="deadline" type="date" class="t-fld">')
    p.append('<label>Izoh (ixtiyoriy)</label><input name="izoh" class="t-fld" placeholder="Qo\'shimcha ko\'rsatma">')
    p.append('<button class="t-save">💾 Topshiriq berish</button>')
    p.append('</form>')

    # JS
    js = (
        '<script>'
        'var VARIANTS=' + variants_js + ';'
        'var PRODS=' + prod_js + ';'
        'function updVariants(){'
        'var wt=document.getElementById("wt").value;'
        'var sel=document.getElementById("variant");'
        'var vs=VARIANTS[wt]||["Standart"];'
        'sel.innerHTML="";'
        'vs.forEach(function(v){var o=document.createElement("option");o.value=v;o.textContent=v;sel.appendChild(o);});'
        '}'
        'function checkMat(){'
        'var pid=document.getElementById("prod").value;'
        'var tgt=parseFloat(document.getElementById("target").value)||0;'
        'var box=document.getElementById("mat-check");'
        'if(!pid){box.innerHTML="";return;}'
        'var pr=PRODS[pid];if(!pr){box.innerHTML="";return;}'
        'if(tgt<=0){box.innerHTML="";return;}'
        'if(pr.miqdor>=tgt){'
        'box.className="mat-check mat-ok";'
        'box.innerHTML="✅ "+pr.name+": "+Math.round(pr.miqdor)+" "+pr.birlik+" bor — yetarli";'
        '}else{'
        'box.className="mat-check mat-warn";'
        'box.innerHTML="⚠️ "+pr.name+": faqat "+Math.round(pr.miqdor)+" "+pr.birlik+" bor — "+Math.round(tgt-pr.miqdor)+" yetishmaydi!";'
        '}}'
        'updVariants();'
        '</script>'
    )
    p.append(js)
    p.append(_TASK_CSS)
    return web.Response(text=_base("Yangi topshiriq", "topshiriqlar", "\n".join(p)), content_type="text/html")


@_require_role("admin")
async def topshiriq_yangi_post(request: web.Request):
    sess = _current(request)
    data = await request.post()
    try:
        worker_id = int(data.get("worker_id"))
        work_type = WorkType(data.get("work_type"))
        target = float(data.get("target_soni") or 0)
    except (ValueError, TypeError):
        return web.HTTPFound("/web/topshiriqlar/yangi")
    if target <= 0:
        return web.HTTPFound("/web/topshiriqlar/yangi")

    variant = (data.get("razmer_turi") or "").strip() or None
    if variant == "Standart":
        variant = None
    product_id = data.get("product_id") or None
    try:
        product_id = int(product_id) if product_id else None
    except ValueError:
        product_id = None
    deadline = None
    dl_raw = (data.get("deadline") or "").strip()
    if dl_raw:
        try:
            deadline = datetime.strptime(dl_raw, "%Y-%m-%d").date()
        except ValueError:
            deadline = None

    async with AsyncSessionLocal() as db:
        db.add(Topshiriq(
            worker_id=worker_id,
            admin_id=sess.get("user_id"),
            work_type=work_type,
            razmer_turi=variant,
            target_soni=target,
            done_soni=0,
            product_id=product_id,
            deadline=deadline,
            status=TopshiriqStatus.tayinlangan,
            izoh=(data.get("izoh") or "").strip() or None,
        ))
        await db.commit()
    raise web.HTTPFound("/web/topshiriqlar")


# ─── 3. QISMAN TOPSHIRIQ QARORI ──────────────────────────────────────────
@_require_role("admin")
async def topshiriq_decide(request: web.Request):
    try:
        data = await request.json()
        tid = int(data.get("task_id", 0))
        action = str(data.get("action", ""))
    except Exception:
        return web.json_response({"ok": False})
    async with AsyncSessionLocal() as db:
        tp = await db.get(Topshiriq, tid)
        if not tp:
            return web.json_response({"ok": False})
        if action == "close":
            # Bajarilgan miqdor qabul, topshiriq yopiladi
            tp.status = TopshiriqStatus.yakunlangan
            tp.completed_at = datetime.now()
        elif action == "keep":
            # Qolgan miqdor uchun davom — target qolgan miqdorga tushadi
            rem = float(tp.target_soni or 0) - float(tp.done_soni or 0)
            tp.target_soni = max(rem, 0)
            tp.done_soni = 0
            tp.status = TopshiriqStatus.tayinlangan
        await db.commit()
    return web.json_response({"ok": True})


_TASK_LIST_JS = (
    '<script>'
    'function decide(tid,act){'
    'var msg=act==="close"?"Topshiriqni yopib, bajarilgan miqdorni qabul qilasizmi?":"Qolgan miqdor uchun topshiriqni davom ettirasizmi?";'
    'if(!confirm(msg))return;'
    'fetch("/web/topshiriqlar/qaror",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({task_id:tid,action:act})}).then(function(r){return r.json();}).then(function(d){'
    'if(d.ok)location.reload();else alert("Xato");});}'
    '</script>'
)


_TASK_CSS = """
<style>
.t-new-btn { background:linear-gradient(135deg,#6366f1,#4f46e5); color:#fff; text-decoration:none;
  padding:10px 16px; border-radius:10px; font-weight:700; font-size:14px; white-space:nowrap }
.t-tabs { display:flex; gap:8px; overflow-x:auto; margin-bottom:16px; padding-bottom:6px }
.t-tab { white-space:nowrap; padding:8px 14px; border-radius:20px; background:var(--bg2);
  border:1px solid var(--border); color:var(--fg); text-decoration:none; font-size:13px; font-weight:600 }
.t-tab-on { background:#6366f1; color:#fff; border-color:#6366f1 }
.t-card { background:var(--bg2); border:1px solid var(--border); border-radius:14px; padding:16px; margin-bottom:12px }
.t-card-head { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px }
.t-worker { font-weight:700; font-size:15px }
.t-work { font-size:13px; color:var(--muted); margin-top:2px; text-transform:capitalize }
.t-badge { color:#fff; border-radius:20px; padding:3px 12px; font-size:12px; font-weight:700; white-space:nowrap }
.t-prog-row { display:flex; justify-content:space-between; font-size:13px; color:var(--muted); margin-bottom:5px }
.t-prog { height:8px; background:var(--bg); border-radius:6px; overflow:hidden }
.t-prog-fill { height:100%; background:linear-gradient(90deg,#3b82f6,#10b981); border-radius:6px; transition:width .3s }
.t-decide { margin-top:14px; padding:12px; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.3); border-radius:12px }
.t-decide-lbl { font-size:13px; font-weight:700; color:#fbbf24; margin-bottom:8px }
.t-decide-btns { display:flex; gap:8px; flex-wrap:wrap }
.t-db { padding:9px 14px; border:none; border-radius:10px; font-weight:700; font-size:13px; cursor:pointer; color:#fff }
.t-close { background:#10b981 }
.t-keep { background:#3b82f6 }

.t-form { display:flex; flex-direction:column; gap:4px; max-width:520px }
.t-form label { font-size:13px; color:var(--muted); font-weight:600; margin-top:10px }
.t-fld { padding:12px 14px; border-radius:10px; border:1px solid var(--border); background:var(--bg2); color:var(--fg); font-size:15px }
.t-save { margin-top:18px; padding:15px; border:none; border-radius:12px; background:linear-gradient(135deg,#10b981,#059669); color:#fff; font-weight:800; font-size:16px; cursor:pointer }
.mat-check { margin-top:8px; padding:0; font-size:14px; font-weight:600 }
.mat-check.mat-ok { padding:12px; border-radius:10px; background:rgba(16,185,129,0.12); color:#34d399 }
.mat-check.mat-warn { padding:12px; border-radius:10px; background:rgba(245,158,11,0.12); color:#fbbf24 }
</style>
"""


def register_topshiriq_routes(app: web.Application):
    app.router.add_get("/web/topshiriqlar", topshiriqlar)
    app.router.add_get("/web/topshiriqlar/yangi", topshiriq_yangi)
    app.router.add_post("/web/topshiriqlar/yangi", topshiriq_yangi_post)
    app.router.add_post("/web/topshiriqlar/qaror", topshiriq_decide)
