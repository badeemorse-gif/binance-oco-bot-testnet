"""Text rendering for the read-only screens (M1).

عرض نصّي مؤقّت لواجهة القراءة (جدول الأوامر / Selected OCO / Dashboard) ضمن CLI،
التزامًا بأعمدة/حقول Deliverable 3. (الواجهة الرسومية RTL الكاملة تُبنى لاحقًا.)
دوال خالصة تُرجع نصًّا لتسهيل الاختبار.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List

from ocobot.domain.models import OcoOrder, SelectedOCO, fmt
from ocobot.domain.reposition import ExecutionResult, ExecutionState, GateResult, RepositionDraft
from ocobot.domain.selection import DashboardSnapshot

# أعمدة جدول Open OCO Orders (screen B) — أسماء إنجليزية كما في التصميم
ORDER_COLUMNS = [
    ("#", 3),
    ("Order List ID", 15),
    ("Symbol", 12),
    ("Status", 12),
    ("Qty", 14),
    ("Sale/TP", 16),
    ("Stop Trigger", 16),
    ("Limit After Trigger", 20),
]


def _cell(text: str, width: int) -> str:
    text = str(text)
    if len(text) >= width:
        return text[: width - 1] + " "
    return text.ljust(width)


def render_orders_table(ocos: List[OcoOrder]) -> str:
    header = "".join(_cell(name, w) for name, w in ORDER_COLUMNS)
    sep = "-" * len(header)
    lines = ["Open OCO Orders  (المصدر: GET /api/v3/openOrderList)", header, sep]
    if not ocos:
        lines.append("لا توجد أوامر OCO مفتوحة.")
        return "\n".join(lines)
    for idx, oco in enumerate(ocos, start=1):
        row = oco.to_row()
        values = [
            idx,
            row["orderListId"],
            row["symbol"],
            row["status"],
            row["qty"],
            row["saleTp"],
            row["stopTrigger"],
            row["limitAfterTrigger"],
        ]
        lines.append("".join(_cell(v, w) for v, (_, w) in zip(values, ORDER_COLUMNS)))
    lines.append("")
    lines.append("اختر أمرًا: python -m ocobot select <orderListId>")
    return "\n".join(lines)


def render_selected_oco(sel: SelectedOCO) -> str:
    f = sel.filters
    lines = [
        "Selected OCO — تأكيد الفهم (Live context مؤسَّس)",
        f"  Order List ID : {sel.order_list_id}",
        f"  Symbol        : {sel.symbol}",
        f"  Quantity      : {fmt(sel.quantity)}  \U0001f512 مقفولة (Read-only)",
        f"  TP            : {fmt(sel.tp)}",
        f"  Stop Trigger  : {fmt(sel.stop_trigger)}",
        f"  Stop Limit    : {fmt(sel.stop_limit)}",
        f"  Leg IDs       : {', '.join(str(x) for x in sel.leg_ids) or '—'}",
        f"  Status        : {sel.status or '—'}",
        f"  Current Price : {fmt(sel.current_price)}  (يصل حيًّا مع المراقبة — T4)",
    ]
    if f is not None:
        lines += [
            "  Filters (exchangeInfo):",
            f"    tickSize    : {fmt(f.tick_size)}",
            f"    stepSize    : {fmt(f.step_size)}",
            f"    minQty      : {fmt(f.min_qty)}",
            f"    minNotional : {fmt(f.min_notional)}",
        ]
    return "\n".join(lines)


def render_dashboard(snap: DashboardSnapshot, has_selection: bool) -> str:
    title = "Dashboard (قراءة فقط)"
    if not has_selection:
        title += "  —  لم يُختَر أمر بعد"
    d = snap.to_dict()
    lines = [
        title,
        f"  Selected OCO     : {d['selectedOco']}",
        f"  Symbol           : {d['symbol']}",
        f"  Current Price    : {d['currentPrice']}",
        f"  Current TP       : {d['currentTp']}",
        f"  Current SL       : {d['currentSl']}",
        f"  Reference Price  : {d['referencePrice']}",
        f"  Next Trigger     : {d['nextTrigger']}",
        f"  Monitoring State : {d['monitoringState']}",
        f"  Connection       : {d['connection']}",
        f"  Last Reposition  : {d['lastReposition']}",
        f"  Environment      : {d['environment']}",
    ]
    return "\n".join(lines)


# ============================ M2: Reposition (T3) ============================

def _arrow(old, new) -> str:
    """يعرض القيمة القديمة → الجديدة (old→new)."""
    return f"{fmt(old)} \u2192 {fmt(new)}"


def render_draft(draft, gate) -> str:
    """مسودّة إعادة التموضع (قراءة فقط — P2). تُظهر old→new و🔒 والترتيب الصارم."""
    if draft is None:
        return "\u26d4 تعذّر بناء المسودّة (لا توجد بيانات)."
    lines = [
        "Manual Edit Draft — مسودّة إعادة تموضع (Read-only، D6)",
        f"  Symbol         : {draft.symbol}  (side={draft.side})",
        f"  Quantity       : {fmt(draft.quantity)}  \U0001f512 Read-only (المتبقية، D7)",
        f"  Reference Price: {fmt(draft.reference_price)}  (مُدخَل صريح — D14)",
        f"  TP  ({fmt(draft.tp_pct)}%)   : {_arrow(draft.old_tp, draft.tp_price)}",
        f"  SL  ({fmt(draft.sl_pct)}%)   : {_arrow(draft.old_stop_trigger, draft.stop_trigger)}  (Stop Trigger)",
        f"  Stop Limit     : {_arrow(draft.old_stop_limit, draft.stop_limit)}  (gap_ticks={draft.gap_ticks}, D5)",
    ]

    # سطر الترتيب الصارم: Stop Limit < Trigger < Last < TP (D4)
    ref = draft.reference_price
    lim, trg, tp = draft.stop_limit, draft.stop_trigger, draft.tp_price
    ok = None not in (lim, trg, ref, tp) and (lim < trg < ref < tp)
    glyph = "\u2713" if ok else "\u2717"
    lines.append(
        f"  {glyph} الترتيب الصارم (D4): Stop Limit({fmt(lim)}) < Trigger({fmt(trg)}) "
        f"< Last({fmt(ref)}) < TP({fmt(tp)})"
    )

    # ملخّص البوابة
    if gate is not None:
        if gate.ok:
            lines.append("  Gate (D16)     : \u2713 اجتازت كل الفحوص — جاهزة للـ Activate.")
        else:
            lines.append("  Gate (D16)     : \u2717 فشلت — لن يُلغى الأمر الأصلي:")
            for f in gate.failures:
                lines.append(f"      - {f}")

    lines.append("  ملاحظة: P2 — لا تغيير قبل Activate (المسودّة قراءة فقط).")
    return "\n".join(lines)


_STATUS_GLYPH = {
    "pending": "\u25cb",   # ○
    "done": "\u2705",      # ✅
    "failed": "\u274c",    # ❌
    "skipped": "\u2013",   # –
    "naked": "\u26a0\ufe0f",
}


def render_execution(result: ExecutionResult) -> str:
    """يعرض خطوات التنفيذ السبع مع إبراز صريح للنافذة العارية (D19) + الحالة النهائية."""
    lines = ["Safe Execution — تنفيذ إعادة التموضع (D9/D10/D16/D19)"]

    naked_open = False
    for step in result.steps:
        # افتح شريط النافذة العارية قبل أول خطوة naked_window، وأغلقه بعد آخرها
        if step.naked_window and not naked_open:
            lines.append("  \u26a0\ufe0f  ===== بداية النافذة العارية (Naked Window) — لا إلغاء ذرّي (D19) =====")
            naked_open = True
        glyph = _STATUS_GLYPH.get(step.status, "\u25cb")
        detail = f"  — {step.detail}" if step.detail else ""
        lines.append(f"  {glyph} {step.label}{detail}")
        # أغلق الشريط بعد آخر خطوة naked
        is_last_naked = step.naked_window and step is _last_naked_step(result.steps)
        if is_last_naked and naked_open:
            lines.append("  \u26a0\ufe0f  ===== نهاية النافذة العارية (Naked Window) =====")
            naked_open = False

    lines.append("")
    state = result.state
    lines.append(f"الحالة النهائية: {state.value}")
    if state == ExecutionState.SUCCESS:
        lines.append(f"  OCO الجديد: {result.new_order_list_id}")
        lines.append(f"  الأمر المُلغى: {result.cancelled_order_list_id}")
    elif state == ExecutionState.FAILED_NEEDS_ATTENTION:
        lines.append(f"  {result.reason}")
    elif state == ExecutionState.ABORTED:
        lines.append(f"  السبب: {result.reason}")
        lines.append("  الأمر الأصلي سليم.")
    for msg in result.messages:
        if msg not in (result.reason,):
            lines.append(f"  • {msg}")
    return "\n".join(lines)


def _last_naked_step(steps):
    naked = [s for s in steps if s.naked_window]
    return naked[-1] if naked else None


# ============================ M3: Dynamic Monitoring (T4) ====================

def render_monitoring(state) -> str:
    """لوحة نصّية لحالة المراقبة الديناميكية (M3). لا أسرار.

    يعرض الحالة، الرمز، السعر المرجعي، مستوى التفعيل/التريجر التالي، latched،
    in_flight، orderListId الهدف، tolerance/guard، آخر سعر، والعدّاد (cursor).
    """
    d = state.to_dict()

    # حساب مستوى التفعيل التالي (reference * (1 + trigger%/100)) إن أمكن
    next_trigger = "\u2014"
    ref = state.reference_price
    trig = state.trigger_pct
    if ref is not None and trig is not None:
        activation = ref * (Decimal("1") + trig / Decimal("100"))
        next_trigger = fmt(activation)

    uid = getattr(state, "trade_uid", "")
    sess = getattr(state, "session_no", 0)
    session_identifier = ("#%s.%d" % (uid, sess)) if uid else "—"

    lines = [
        "Dynamic Monitoring — المراقبة الديناميكية (M3، الحالة في الذاكرة)",
        f"  Monitoring State : {d['state']}   (enabled={d['enabled']})",
        f"  Symbol           : {d['symbol']}",
        f"  معرّف الجلسة      : {session_identifier}",
        f"  Reference Price  : {d['referencePrice']}  (سعر حيّ حقيقي — D14)",
        f"  Trigger Rise     : {d['triggerPct']}%",
        f"  Next Trigger     : {next_trigger}  (مستوى التفعيل)",
        f"  TP / SL          : {d['tpPct']}% / {d['slPct']}%",
        f"  Latched          : {d['latched']}",
        f"  In Flight        : {d['inFlight']}  (One-Replacement-In-Flight)",
        f"  Target OrderList : {d['targetOrderListId']}",
        f"  Tolerance / Guard: {d['tolerancePct']}% / {d['guardPct']}%",
        f"  Last Price       : {d['lastPrice']}",
        f"  Repositions      : {d['cursor']}  (cursor)",
    ]
    if d.get("lastReposition"):
        lr = d["lastReposition"]
        lines.append(
            f"  Last Reposition  : #{lr.get('cursor')} -> OCO {lr.get('newOrderListId')} "
            f"@ {lr.get('referencePrice')}"
        )
    return "\n".join(lines)
