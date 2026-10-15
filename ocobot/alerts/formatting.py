"""ocobot.alerts.formatting — MarkdownV2 message formatters for Telegram alerts.

Pure stdlib + decimal. NO Qt, NO network, NO secret/token handling.

These functions turn audit records (and optional MonitoringState) into
MarkdownV2-escaped strings suitable for ``Notifier.enqueue(text)`` whose
default ``parse_mode`` is ``MarkdownV2``.

Design rules:
  * Every dynamic value is passed through :func:`escape_mdv2` before being
    embedded in the message body. Emoji and the fixed plain-text labels are
    NOT escaped.
  * All field access is defensive (``.get(...)`` with a ``"—"`` fallback).
  * The functions must NEVER raise. On any unexpected error they degrade to a
    best-effort / partial message rather than propagating an exception.
  * ``compute_levels`` is intentionally NOT used (it needs ``tick_size`` which
    audit records do not carry). Derived prices use simple fallback formulas.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

__all__ = [
    "escape_mdv2",
    "build_monitor_start_message",
    "build_reposition_message",
    "build_guardian_message",
    "build_market_exit_message",
    "build_btc_follow_message",
    "build_manual_exit_message",
    "build_monitor_closed_message",
    "format_event",
]

# Fallback shown for any missing / unresolvable value.
_MISSING = "—"

# MarkdownV2 reserved characters that must be backslash-escaped.
_MDV2_SPECIAL = set("_*[]()~`>#+-=|{}.!")

# Fixed emoji (literal, never escaped).
_EMOJI_TP = "🟢"   # take-profit price
_EMOJI_SL = "🔴"   # stop-loss price
_EMOJI_PRICE = "🟡"  # current / last price


def escape_mdv2(text: Any) -> str:
    """Return *text* coerced to ``str`` with every MarkdownV2 special char
    backslash-escaped.

    The escaped characters are: ``_ * [ ] ( ) ~ ` > # + - = | { } . !``
    Emoji and ordinary letters/digits are left untouched. Never raises.
    """
    try:
        s = str(text)
    except Exception:
        return _MISSING
    out = []
    for ch in s:
        if ch in _MDV2_SPECIAL:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Best-effort conversion of a possibly-string value to ``Decimal``.

    Audit records serialize Decimals as strings, so we accept str/int/float/
    Decimal. Returns ``None`` when conversion is impossible. Never raises.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _fmt_decimal(value: Any) -> str:
    """Human-friendly, MarkdownV2-escaped representation of a numeric value.

    Falls back to the raw escaped value when it is not Decimal-convertible,
    and to ``_MISSING`` when the value is absent. Never raises.
    """
    if value is None:
        return _MISSING
    dec = _to_decimal(value)
    if dec is None:
        # Not numeric; show the raw value, escaped.
        return escape_mdv2(value)
    # Normalize: drop meaningless trailing zeros but keep a plain decimal form.
    try:
        normalized = dec.normalize()
        text = format(normalized, "f")
    except (InvalidOperation, ValueError):
        text = str(dec)
    return escape_mdv2(text)


def _fmt_pct(value: Any) -> str:
    """Format a percent value (already a percentage number) escaped for MDV2."""
    if value is None:
        return _MISSING
    dec = _to_decimal(value)
    if dec is None:
        return escape_mdv2(value)
    try:
        normalized = dec.normalize()
        text = format(normalized, "f")
    except (InvalidOperation, ValueError):
        text = str(dec)
    return escape_mdv2(text + "%")


def _plain_pct(value: Any) -> str:
    """صيغة نصية مُطبّعة لنسبة (بلا تهريب MDV2) لإدراجها داخل سطر reason.

    تُستعمل داخل نصّ reason للـBTC حيث يمرّ السطر لاحقًا عبر ``escape_mdv2`` كجزء
    من القيمة في ``_label_str``. ``_MISSING`` عند غياب القيمة. لا يرمي أبدًا.
    """
    if value is None:
        return _MISSING
    dec = _to_decimal(value)
    if dec is None:
        try:
            return str(value)
        except Exception:
            return _MISSING
    try:
        return format(dec.normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(dec)


def _derive_price(reference: Any, pct: Any, *, add: bool) -> Optional[Decimal]:
    """Compute reference*(1 ± pct/100) as Decimal, or None if inputs invalid."""
    ref = _to_decimal(reference)
    p = _to_decimal(pct)
    if ref is None or p is None:
        return None
    try:
        factor = Decimal(1) + (p / Decimal(100)) if add else Decimal(1) - (p / Decimal(100))
        return ref * factor
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _get(mapping: Any, key: str, default: Any = None) -> Any:
    """Safe ``.get`` that tolerates non-dict inputs."""
    if isinstance(mapping, dict):
        return mapping.get(key, default)
    return default


def _state_attr(state: Any, name: str, default: Any = None) -> Any:
    """Safe attribute access on a MonitoringState-like object."""
    if state is None:
        return default
    try:
        return getattr(state, name, default)
    except Exception:
        return default


def _session_id(trade_uid: Any, session_no: Any) -> str:
    """Build the session id '#%s.%d' % (trade_uid, session_no), escaped.

    Degrades gracefully when either part is missing/invalid.
    """
    if trade_uid is None and session_no is None:
        return _MISSING
    try:
        sno = int(session_no)
        raw = "#%s.%d" % (trade_uid, sno)
    except (TypeError, ValueError):
        # Fall back to a loose join without crashing.
        tu = trade_uid if trade_uid is not None else _MISSING
        sn = session_no if session_no is not None else _MISSING
        raw = "#%s.%s" % (tu, sn)
    return escape_mdv2(raw)


def _timestamp(record: Any, details: Any) -> str:
    """Prefer record['ts'], else details.start_ts. Escaped. Never raises."""
    ts = _get(record, "ts")
    if ts is None:
        ts = _get(details, "start_ts")
    if ts is None:
        return _MISSING
    return escape_mdv2(ts)


def _plan_get(details: Any, key: str, default: Any = None) -> Any:
    """Safely read ``details['plan'][key]`` tolerating a missing/non-dict plan."""
    plan = _get(details, "plan")
    return _get(plan, key, default)


def _response_order_id(details: Any) -> Any:
    """Pull an order id from a brokerage response dict, trying common keys.

    Looks at ``details['response']`` for ``id`` / ``orderId`` / ``clientOrderId``
    in that order. Returns ``None`` when nothing is present. Never raises.
    """
    response = _get(details, "response")
    if not isinstance(response, dict):
        return None
    for key in ("id", "orderId", "clientOrderId"):
        val = response.get(key)
        if val is not None:
            return val
    return None


def _label_str(label: str, value: Any) -> str:
    """``label`` + escaped string value, degrading to ``_MISSING`` when absent."""
    if value is None:
        return label + _MISSING
    return label + escape_mdv2(value)


def _pnl_pct(entry: Any, exit_price: Any) -> str:
    """نسبة الربح/الخسارة ‪(exit-entry)/entry*100‬ مُنسّقة لـMarkdownV2، أو ``_MISSING``.

    دفاعي بالكامل: إن غاب أيٌّ منهما أو كان ``entry == 0`` أو تعذّر الحساب ⇒
    ``_MISSING``. لا يرمي أبدًا.
    """
    try:
        e = _to_decimal(entry)
        x = _to_decimal(exit_price)
        if e is None or x is None or e == Decimal(0):
            return _MISSING
        pct = (x - e) / e * Decimal(100)
        return _fmt_pct(pct)
    except (InvalidOperation, ValueError, ArithmeticError, TypeError):
        return _MISSING


def _standard_field_lines(*, symbol, reason, entry, exit_price, quantity,
                          order_id, client_order_id, time_str):
    """أسطر الحقول القياسية الموحّدة لرسائل التدخّل الأربع (مُهرّبة لـMDV2).

    تُستعمل القيم المُمرّرة مباشرةً عبر الدوال المساعدة القائمة. دفاعي؛ يُفترض أن
    يُستدعى داخل ``try`` في الباني. ``PnL%`` تُحسب من ‪entry→exit_price‬.
    """
    return [
        _label_str("Symbol: ", symbol),
        _label_str("Reason: ", reason),
        "Entry: " + _fmt_decimal(entry),
        "Exit price: " + _fmt_decimal(exit_price),
        "PnL%: " + _pnl_pct(entry, exit_price),
        "Quantity: " + _fmt_decimal(quantity),
        _label_str("Order id: ", order_id),
        _label_str("Client order id: ", client_order_id),
        "Time: " + time_str,
    ]


def build_monitor_start_message(record: Any, state: Optional[Any] = None) -> str:
    """Render a MarkdownV2 message for a ``monitor_start`` audit record."""
    try:
        details = _get(record, "details", {}) or {}

        trade_uid = _get(details, "trade_uid", _state_attr(state, "trade_uid"))
        session_no = _get(details, "session_no", _state_attr(state, "session_no"))
        session = _session_id(trade_uid, session_no)

        symbol = _get(details, "symbol", _state_attr(state, "symbol"))
        target = _get(details, "order_list_id",
                      _state_attr(state, "target_order_list_id"))

        reference_price = _get(details, "reference_price",
                               _state_attr(state, "reference_price"))
        trigger_pct = _get(details, "trigger_pct", _state_attr(state, "trigger_pct"))
        tp_pct = _get(details, "tp_pct", _state_attr(state, "tp_pct"))
        sl_pct = _get(details, "sl_pct", _state_attr(state, "sl_pct"))

        last_price = _state_attr(state, "last_price")

        tp_price = _derive_price(reference_price, tp_pct, add=True)
        sl_price = _derive_price(reference_price, sl_pct, add=False)
        activation = _derive_price(reference_price, trigger_pct, add=True)

        lines = [
            "🚀 *Monitor Started*",
            "",
            "Session: " + session,
            "Symbol: " + _fmt_decimal(symbol) if not isinstance(symbol, str)
            else "Symbol: " + escape_mdv2(symbol),
            "Order list: " + (escape_mdv2(target) if target is not None else _MISSING),
            "",
            "Reference price: " + _fmt_decimal(reference_price),
            "Last price: " + _EMOJI_PRICE + " " + _fmt_decimal(last_price),
            "Activation \\(next\\): " + _fmt_decimal(activation)
            + "  \\(" + _fmt_pct(trigger_pct) + "\\)",
            "",
            "TP: " + _EMOJI_TP + " " + _fmt_decimal(tp_price)
            + "  \\(" + _fmt_pct(tp_pct) + "\\)",
            "SL: " + _EMOJI_SL + " " + _fmt_decimal(sl_price)
            + "  \\(" + _fmt_pct(sl_pct) + "\\)",
            "",
            "Time: " + _timestamp(record, details),
        ]
        return "\n".join(lines)
    except Exception:
        # Absolute last-resort: never raise.
        return "🚀 *Monitor Started*\n" + escape_mdv2(
            "(partial: formatting error)")


def build_reposition_message(record: Any, state: Optional[Any] = None,
                             prev_price: Optional[Any] = None) -> str:
    """Render a MarkdownV2 message for a ``repositioned`` audit record."""
    try:
        details = _get(record, "details", {}) or {}

        # G1.36: اقرأ سياق الجلسة من details أولًا (كـ monitor_start) ثم state،
        #        فتُعبّأ الخانات في مسار الجسر (state=None) عبر الدمج في bridge.py.
        trade_uid = _get(details, "trade_uid", _state_attr(state, "trade_uid"))
        session_no = _get(details, "session_no", _state_attr(state, "session_no"))
        session = _session_id(trade_uid, session_no)

        symbol = _get(details, "symbol", _state_attr(state, "symbol"))

        new_target = _get(details, "new_target",
                          _state_attr(state, "target_order_list_id"))
        old_target = _get(details, "old_target")

        cursor = _get(details, "cursor", _state_attr(state, "cursor"))

        current_price = _get(details, "price", _state_attr(state, "last_price"))

        # Previous price: explicit prev_price arg, else state.last_reposition.
        previous_price = prev_price
        if previous_price is None:
            last_repo = _state_attr(state, "last_reposition")
            if isinstance(last_repo, dict):
                previous_price = last_repo.get("price")

        reference_price = _get(details, "reference_price",
                               _state_attr(state, "reference_price"))
        trigger_pct = _get(details, "trigger_pct", _state_attr(state, "trigger_pct"))
        tp_pct = _get(details, "tp_pct", _state_attr(state, "tp_pct"))
        sl_pct = _get(details, "sl_pct", _state_attr(state, "sl_pct"))

        tp_price = _derive_price(reference_price, tp_pct, add=True)
        sl_price = _derive_price(reference_price, sl_pct, add=False)
        activation = _derive_price(reference_price, trigger_pct, add=True)

        lines = [
            "🔁 *Repositioned*",
            "",
            "Session: " + session,
            "Symbol: " + (escape_mdv2(symbol) if symbol is not None else _MISSING),
            "Order list \\(current\\): "
            + (escape_mdv2(new_target) if new_target is not None else _MISSING),
            "Order list \\(previous\\): "
            + (escape_mdv2(old_target) if old_target is not None else _MISSING),
            "",
            "Current price: " + _EMOJI_PRICE + " " + _fmt_decimal(current_price),
        ]

        # Previous price is optional — omit gracefully if absent.
        if previous_price is not None:
            lines.append("Previous price: " + _fmt_decimal(previous_price))

        lines.extend([
            "Reference price: " + _fmt_decimal(reference_price),
            "Activation \\(next\\): " + _fmt_decimal(activation)
            + "  \\(" + _fmt_pct(trigger_pct) + "\\)",
            "",
            "TP: " + _EMOJI_TP + " " + _fmt_decimal(tp_price)
            + "  \\(" + _fmt_pct(tp_pct) + "\\)",
            "SL: " + _EMOJI_SL + " " + _fmt_decimal(sl_price)
            + "  \\(" + _fmt_pct(sl_pct) + "\\)",
            "",
            "Cursor: " + (escape_mdv2(cursor) if cursor is not None else _MISSING),
            "Time: " + _timestamp(record, details),
        ])
        return "\n".join(lines)
    except Exception:
        return "🔁 *Repositioned*\n" + escape_mdv2("(partial: formatting error)")


def build_guardian_message(record: Any, state: Optional[Any] = None) -> str:
    """Render a MarkdownV2 message for a ``guardian_intervention`` record.

    Fired ONLY on an actual protective-stop placement. Shows every available
    field; each missing value degrades to ``_MISSING``. Never raises.
    """
    try:
        details = _get(record, "details", {}) or {}

        symbol = _get(details, "symbol", _state_attr(state, "symbol"))
        reason = _get(details, "reason")
        action = _get(details, "action")

        quantity = _get(details, "eff_qty")
        if quantity is None:
            quantity = _plan_get(details, "quantity")

        reference_price = _get(details, "reference_price")
        stop_trigger = _plan_get(details, "stop_trigger")
        if stop_trigger is None:
            stop_trigger = _plan_get(details, "stop_price")
        stop_limit = _plan_get(details, "limit_price")
        emergency_sl_pct = _get(details, "emergency_sl_pct")
        client_order_id = _get(details, "client_order_id")
        order_id = _response_order_id(details)
        naked_seconds = _get(details, "naked_seconds")

        # G1.57: Exit price للحارس = stop_trigger ثم stop_price (أول متاح).
        exit_price = stop_trigger if stop_trigger is not None else stop_limit
        if exit_price is None:
            exit_price = _plan_get(details, "stop_price")

        lines = [
            "🛡️ *Position Guardian*",
            "",
            _label_str("Symbol: ", symbol),
            _label_str("Reason: ", reason),
            _label_str("Action: ", action),
            "Quantity: " + _fmt_decimal(quantity),
            "Reference price: " + _fmt_decimal(reference_price),
            # G1.57: الحقول القياسية الموحّدة (Entry/Exit price/PnL%).
            "Entry: " + _fmt_decimal(reference_price),
            "Exit price: " + _fmt_decimal(exit_price),
            "PnL%: " + _pnl_pct(reference_price, exit_price),
            "Stop trigger: " + _EMOJI_SL + " " + _fmt_decimal(stop_trigger),
            "Stop limit: " + _fmt_decimal(stop_limit),
            "Emergency SL: " + _fmt_pct(emergency_sl_pct),
            _label_str("Client order id: ", client_order_id),
            _label_str("Order id: ", order_id),
            "Naked seconds: " + _fmt_decimal(naked_seconds),
            "Time: " + _timestamp(record, details),
        ]
        return "\n".join(lines)
    except Exception:
        # Absolute last-resort: never raise.
        return "🛡️ *Position Guardian*\n" + escape_mdv2(
            "(partial: formatting error)")


def build_market_exit_message(record: Any, state: Optional[Any] = None) -> str:
    """Render a MarkdownV2 message for a ``market_exit`` record.

    Fired ONLY on an actual bracket exit placement. Shows every available
    field; each missing value degrades to ``_MISSING``. Never raises.
    """
    try:
        details = _get(record, "details", {}) or {}

        symbol = _get(details, "symbol", _state_attr(state, "symbol"))
        exit_side = _get(details, "exit_side")
        action = _get(details, "action")

        quantity = _get(details, "eff_qty")
        if quantity is None:
            quantity = _plan_get(details, "quantity")

        order_type = _plan_get(details, "type")
        stop_price = _plan_get(details, "stop_price")
        stop_limit = _plan_get(details, "limit_price")
        limit_price = _plan_get(details, "price")
        price_floor = _plan_get(details, "price_floor")
        reference_price = _get(details, "reference_price")
        client_order_id = _get(details, "client_order_id")
        order_id = _response_order_id(details)

        # G1.57: Exit price = plan price → limit_price → stop_price (أول متاح).
        exit_price = limit_price
        if exit_price is None:
            exit_price = stop_limit
        if exit_price is None:
            exit_price = stop_price

        # G1.57: لاحقة الجهة في الرأس من exit_side (مُهرّبة لـMarkdownV2).
        side = str(exit_side).strip().lower() if exit_side is not None else ""
        if side == "upper":
            header = "🧷 *Price Exit Bracket* \\(Upper\\)"
        elif side == "lower":
            header = "🧷 *Price Exit Bracket* \\(Lower\\)"
        else:
            header = "🧷 *Price Exit Bracket*"

        lines = [
            header,
            "",
            _label_str("Symbol: ", symbol),
            _label_str("Exit side: ", exit_side),
            _label_str("Action: ", action),
            "Quantity: " + _fmt_decimal(quantity),
            # G1.57: الحقول القياسية الموحّدة (Entry/Exit price/PnL%).
            "Entry: " + _fmt_decimal(reference_price),
            "Exit price: " + _fmt_decimal(exit_price),
            "PnL%: " + _pnl_pct(reference_price, exit_price),
            _label_str("Order type: ", order_type),
            "Stop price: " + _EMOJI_SL + " " + _fmt_decimal(stop_price),
            "Stop limit: " + _fmt_decimal(stop_limit),
            "Limit price: " + _fmt_decimal(limit_price),
            "Price floor: " + _fmt_decimal(price_floor),
            "Reference price: " + _fmt_decimal(reference_price),
            _label_str("Client order id: ", client_order_id),
            _label_str("Order id: ", order_id),
            "Time: " + _timestamp(record, details),
        ]
        return "\n".join(lines)
    except Exception:
        # Absolute last-resort: never raise.
        return "🧷 *Price Exit Bracket*\n" + escape_mdv2(
            "(partial: formatting error)")


def build_btc_follow_message(record: Any, state: Optional[Any] = None) -> str:
    """Render a MarkdownV2 message for a ``btc_follow_intervention`` record.

    Fired ONLY on an actual defensive-tighten exit placement by the BTC-drop
    guard. Shows the unified standard fields. Defensive; never raises.
    """
    try:
        details = _get(record, "details", {}) or {}

        symbol = _get(details, "symbol", _state_attr(state, "symbol"))
        drop_pct = _get(details, "drop_pct")
        reason = "BTC drop confirmed (~" + _plain_pct(drop_pct) + "%)"

        quantity = _get(details, "eff_qty")
        if quantity is None:
            quantity = _plan_get(details, "quantity")

        reference_price = _get(details, "reference_price")
        exit_price = _plan_get(details, "price")
        if exit_price is None:
            exit_price = _plan_get(details, "limit_price")
        if exit_price is None:
            exit_price = _plan_get(details, "stop_price")

        client_order_id = _get(details, "client_order_id")
        order_id = _response_order_id(details)

        lines = ["⬇️ *BTC\\-Follow Guard*", ""]
        lines.extend(_standard_field_lines(
            symbol=symbol,
            reason=reason,
            entry=reference_price,
            exit_price=exit_price,
            quantity=quantity,
            order_id=order_id,
            client_order_id=client_order_id,
            time_str=_timestamp(record, details),
        ))
        return "\n".join(lines)
    except Exception:
        # Absolute last-resort: never raise.
        return "⬇️ *BTC\\-Follow Guard*\n" + escape_mdv2(
            "(partial: formatting error)")


# G1.63: ملاحظات إنجليزية موجزة لنتيجة عدم تنفيذ الخروج اليدوي (§1.5: لا عربية في Telegram).
_MANUAL_EXIT_OUTCOME_NOTES = {
    "ABORT_GATE": "blocked by the double sell safety gate",
    "ABORT_PROTECTED": "a protective sell order already rests",
    "ABORT_NO_FREE_QTY": "no free balance to sell; it is locked in a resting order",
    "ABORT_NO_SELECTION": "no trade is selected",
    "ABORT_INVALID_FILTERS": "invalid symbol filters",
    "ERROR": "an internal error prevented the exit",
    "DRY_RUN": "dry run; no live action",
}


def build_manual_exit_message(record: Any, state: Optional[Any] = None) -> str:
    """Render a MarkdownV2 message for a ``manual_exit`` record.

    Fired on an actual manual market-exit placement. Shows the unified standard
    fields. Defensive; never raises.
    """
    try:
        details = _get(record, "details", {}) or {}

        # G1.63: مسار غير المنفَّذ (placed=False) — رسالة إقرار واضحة بالسبب. المسار
        #        القديم لم يكن يُنتَج إطلاقًا لغير المنفَّذ؛ والمنفَّذ (placed=True/None)
        #        يبقى كما هو تمامًا أدناه (لا مساس بأي نجاح).
        if _get(details, "placed") is False:
            symbol_np = _get(details, "symbol", _state_attr(state, "symbol"))
            action_np = _get(details, "action")
            note_np = _MANUAL_EXIT_OUTCOME_NOTES.get(
                str(action_np).strip() if action_np is not None else "",
                "exit was not placed")
            lines_np = [
                "✋ *Manual Exit* \\(not placed\\)",
                "",
                _label_str("Symbol: ", symbol_np),
                _label_str("Action: ", action_np),
                _label_str("Note: ", note_np),
                "Time: " + _timestamp(record, details),
            ]
            return "\n".join(lines_np)

        symbol = _get(details, "symbol", _state_attr(state, "symbol"))
        reason = "Manual exit (best live price)"

        quantity = _get(details, "eff_qty")
        if quantity is None:
            quantity = _plan_get(details, "quantity")

        reference_price = _get(details, "reference_price")
        exit_price = _plan_get(details, "price")
        if exit_price is None:
            exit_price = _plan_get(details, "limit_price")
        if exit_price is None:
            exit_price = _plan_get(details, "stop_price")

        client_order_id = _get(details, "client_order_id")
        order_id = _response_order_id(details)

        lines = ["✋ *Manual Exit*", ""]
        lines.extend(_standard_field_lines(
            symbol=symbol,
            reason=reason,
            entry=reference_price,
            exit_price=exit_price,
            quantity=quantity,
            order_id=order_id,
            client_order_id=client_order_id,
            time_str=_timestamp(record, details),
        ))
        return "\n".join(lines)
    except Exception:
        # Absolute last-resort: never raise.
        return "✋ *Manual Exit*\n" + escape_mdv2(
            "(partial: formatting error)")


# G1.62: تسمية بشرية موجزة لسبب إغلاق الجلسة (EndReason) — بلا رموز MarkdownV2 خاصّة.
_END_REASON_LABELS = {
    "completed_tp": "🟢 Take Profit",
    "completed_sl": "🔴 Stop Loss",
    "stopped_manual": "✋ Stopped manually",
    "stopped_disconnect": "🔌 Stopped on disconnect",
    "stopped_other": "⏹ Stopped",
}


def build_monitor_closed_message(record: Any, state: Optional[Any] = None) -> str:
    """Render a MarkdownV2 message for a ``monitor_closed`` audit record (G1.62).

    Fires on EVERY session close — whether the position exited by a real sell
    (TP/SL fill or an intervention) or the user stopped monitoring. Carries the
    close reason, the operating percentages (trigger/TP/SL) and, for a completed
    TP/SL exit, the resulting PnL% derived from the configured level. Reads the
    session context merged by the bridge (``_enrich``) and/or state. Never raises.
    """
    try:
        details = _get(record, "details", {}) or {}

        trade_uid = _get(details, "trade_uid", _state_attr(state, "trade_uid"))
        session_no = _get(details, "session_no", _state_attr(state, "session_no"))
        session = _session_id(trade_uid, session_no)

        symbol = _get(details, "symbol", _state_attr(state, "symbol"))

        end_reason = _get(details, "end_reason")
        reason_key = str(end_reason).strip().lower() if end_reason is not None else ""
        outcome = _END_REASON_LABELS.get(reason_key, "⏹ Stopped")
        reason_text = _get(details, "reason")

        reference_price = _get(details, "reference_price",
                               _state_attr(state, "reference_price"))
        trigger_pct = _get(details, "trigger_pct", _state_attr(state, "trigger_pct"))
        tp_pct = _get(details, "tp_pct", _state_attr(state, "tp_pct"))
        sl_pct = _get(details, "sl_pct", _state_attr(state, "sl_pct"))

        tp_price = _derive_price(reference_price, tp_pct, add=True)
        sl_price = _derive_price(reference_price, sl_pct, add=False)
        activation = _derive_price(reference_price, trigger_pct, add=True)

        # G1.62: نتيجة الصفقة% عند خروج فعلي بـTP/SL — تُشتقّ من مستوى الإعداد
        #        (TP ⇒ +tp_pct ، SL ⇒ -sl_pct). غير ذلك ⇒ _MISSING.
        result_pct = _MISSING
        if reason_key == "completed_tp" and tp_pct is not None:
            result_pct = _fmt_pct(tp_pct)
        elif reason_key == "completed_sl" and sl_pct is not None:
            neg = _to_decimal(sl_pct)
            result_pct = _fmt_pct(-neg) if neg is not None else _MISSING

        lines = [
            "🏁 *Monitor Closed*",
            "",
            "Session: " + session,
            "Symbol: " + (escape_mdv2(symbol) if symbol is not None else _MISSING),
            "Outcome: " + outcome,
            _label_str("Reason: ", reason_text),
            "Result%: " + result_pct,
            "",
            "Reference price: " + _fmt_decimal(reference_price),
            "Activation \\(next\\): " + _fmt_decimal(activation)
            + "  \\(" + _fmt_pct(trigger_pct) + "\\)",
            "TP: " + _EMOJI_TP + " " + _fmt_decimal(tp_price)
            + "  \\(" + _fmt_pct(tp_pct) + "\\)",
            "SL: " + _EMOJI_SL + " " + _fmt_decimal(sl_price)
            + "  \\(" + _fmt_pct(sl_pct) + "\\)",
            "",
            "Time: " + _timestamp(record, details),
        ]
        return "\n".join(lines)
    except Exception:
        # Absolute last-resort: never raise.
        return "🏁 *Monitor Closed*\n" + escape_mdv2("(partial: formatting error)")


def format_event(record: Any, state: Optional[Any] = None,
                 prev_price: Optional[Any] = None) -> Optional[str]:
    """Route an audit *record* to the matching builder by its ``event``.

    Handles ``monitor_start``, ``repositioned``, ``guardian_intervention`` and
    ``market_exit``; returns ``None`` for any other event. Never raises.
    """
    try:
        event = _get(record, "event")
    except Exception:
        return None
    if event == "monitor_start":
        return build_monitor_start_message(record, state)
    if event == "repositioned":
        return build_reposition_message(record, state, prev_price)
    if event == "guardian_intervention":
        return build_guardian_message(record, state)
    if event == "market_exit":
        return build_market_exit_message(record, state)
    if event == "btc_follow_intervention":
        return build_btc_follow_message(record, state)
    if event == "manual_exit":
        return build_manual_exit_message(record, state)
    if event == "monitor_closed":
        return build_monitor_closed_message(record, state)
    return None
