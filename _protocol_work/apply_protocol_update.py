# -*- coding: utf-8 -*-
"""تطبيق تحديث البروتوكول 1.5 -> 1.6: إضافة البند 11.8 + رفع الإصدار + تحديث الوثائق.

تعديل جراحي يحافظ على باقي PROJECT_STATE.json كما هو (استبدال التمثيل JSON الدقيق
لقيمة system_prompt + حقول الإصدار)، وكتابة ذرّية (ملف مؤقّت ثم os.replace).
idempotent: لو البند موجود/الإصدار 1.6 بالفعل لا يكرّر.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PS = os.path.join(ROOT, "PROJECT_STATE.json")
DL = os.path.join(ROOT, "state", "decisions_log.json")
EXEC_MD = os.path.join(ROOT, "docs", "EXECUTOR_PROMPT_AR.md")
PROMPT_MD = os.path.join(ROOT, "prompt.md")

NEW_VER = "1.6"
OLD_VER = "1.5"
TS = "2026-10-15T22:00:00Z"
MARK = "11.8 قاعدة التجربة التاريخية الافتراضية"

CLAUSE = (
    "**11.8 قاعدة التجربة التاريخية الافتراضية (Historical-First Testing) — "
    "(protocol_version 1.6):** أثناء طور التعديلات وحلّ المشكلات داخل المشروع "
    "(مثل G1_MANUAL_TESTING)، إذا طلب المستخدم «تجربة» أو «نجرّب» لميزة/نقطة معيّنة "
    "دون أن يحدّد الطريقة، فالوضع الافتراضي الإلزامي هو تنفيذ التجربة بالطريقة "
    "التاريخية (Walk-Forward Backtest) على بيانات klines تاريخية حقيقية من مصدر "
    "Binance العام، خارج العيّنة (معايرة على نافذة تدريب ثم قياس على نافذة اختبار "
    "لاحقة)، بهدف تحسين الدقة في النقطة محلّ النقاش بالذات. وهذه التجربة: (أ) بصفر "
    "مخاطرة — محاكاة بحتة بلا أي أوامر حقيقية ولا مسّ لأي رصيد أو أمر على البورصة "
    "(التزامٌ بثوابت الأمان في القسم 1)؛ (ب) تُقارَن دائمًا بخطّ أساس baseline "
    "وبمقاييس صريحة (مثل متوسّط العائد لكل صفقة، والتقاط الحركة MFE، ونسبة الربح) "
    "لتكون النتيجة قابلة للحكم؛ (ج) لا تُعتمَد نتيجتها كتغيير دائم في أي معامل أو "
    "كود إلا بأمر «نفّذ» صريح من المستخدم. ويبقى الاختبار الحيّ/Testnet بأوامر "
    "فعلية خطوةَ تأكيدٍ لاحقة لا تُنفَّذ إلا بطلب صريح، مع بقاء منع أي Live (T16) "
    "قبل بوّابة G1. ولا يُلغي هذا البند حقّ المستخدم في اختيار طريقة مختلفة متى "
    "حدّدها صراحةً."
)


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def surgical_replace(text, old, new, label):
    n = text.count(old)
    if n != 1:
        fail(f"{label}: expected exactly 1 occurrence, found {n}")
    return text.replace(old, new, 1)


# ---------- PROJECT_STATE.json ----------
with open(PS, "r", encoding="utf-8", newline="") as fh:
    raw = fh.read()
ps = json.loads(raw)

already_sp = MARK in ps["system_prompt"]
if ps["protocol_version"] == NEW_VER and already_sp:
    print("PS_ALREADY_APPLIED version=", ps["protocol_version"])
else:
    # 1) system_prompt: استبدال التمثيل JSON الدقيق للقيمة القديمة بالجديدة
    if not already_sp:
        old_sp = ps["system_prompt"]
        new_sp = old_sp.rstrip() + "\r\n\r\n" + CLAUSE
        old_sp_json = json.dumps(old_sp, ensure_ascii=False)
        new_sp_json = json.dumps(new_sp, ensure_ascii=False)
        raw = surgical_replace(raw, old_sp_json, new_sp_json, "system_prompt")
    # 2) protocol_version
    raw = surgical_replace(raw, f'"protocol_version": "{OLD_VER}"',
                           f'"protocol_version": "{NEW_VER}"', "protocol_version")
    # 3) bootstrapped_at (إجراء «حدّث البروتوكول» يوجب تحديثه)
    old_boot = f'"bootstrapped_at": {json.dumps(ps["bootstrapped_at"])}'
    raw = surgical_replace(raw, old_boot, f'"bootstrapped_at": {json.dumps(TS)}',
                           "bootstrapped_at")
    # 4) last_updated إن وُجد
    if "last_updated" in ps:
        old_lu = f'"last_updated": {json.dumps(ps["last_updated"], ensure_ascii=False)}'
        raw = surgical_replace(raw, old_lu, f'"last_updated": {json.dumps(TS)}',
                               "last_updated")

    # تحقق: JSON صالح + الإصدار + البند
    chk = json.loads(raw)
    assert chk["protocol_version"] == NEW_VER, "version not bumped"
    assert MARK in chk["system_prompt"], "clause not in system_prompt"

    tmp = PS + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(raw)
    os.replace(tmp, PS)
    print("PS_UPDATED version=", chk["protocol_version"],
          "sp_len=", len(chk["system_prompt"]),
          "boot=", chk["bootstrapped_at"],
          "last_updated=", chk.get("last_updated"))

# ---------- state/decisions_log.json ----------
with open(DL, "r", encoding="utf-8") as fh:
    dl = json.load(fh)
if not any(isinstance(e, dict) and e.get("decision") == "protocol_updated"
           and e.get("note", "").find("11.8") != -1 for e in dl):
    dl.append({
        "id": "protocol-1.6",
        "decision": "protocol_updated",
        "note": ("أُضيف البند 11.8 (قاعدة التجربة التاريخية الافتراضية) ورُفِع الإصدار "
                 "1.5->1.6 بأمر صريح من المستخدم؛ bootstrapped_at السابق 2026-09-21T23:05:00Z"),
        "ts": TS,
    })
    tmp = DL + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dl, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, DL)
    print("DECISIONS_LOG_APPENDED len=", len(dl))
else:
    print("DECISIONS_LOG_ALREADY len=", len(dl))

# ---------- docs/EXECUTOR_PROMPT_AR.md ----------
with open(EXEC_MD, "r", encoding="utf-8", newline="") as fh:
    md = fh.read()
if MARK not in md:
    nl = "\r\n" if "\r\n" in md else "\n"
    md2 = md.rstrip() + nl + nl + CLAUSE + nl
    tmp = EXEC_MD + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(md2)
    os.replace(tmp, EXEC_MD)
    print("EXECUTOR_MD_APPENDED")
else:
    print("EXECUTOR_MD_ALREADY")

# ---------- prompt.md (رفع رقم الإصدار المذكور) ----------
with open(PROMPT_MD, "r", encoding="utf-8", newline="") as fh:
    pm = fh.read()
if f"protocol_version = {OLD_VER}" in pm:
    pm2 = pm.replace(f"protocol_version = {OLD_VER}", f"protocol_version = {NEW_VER}")
    tmp = PROMPT_MD + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(pm2)
    os.replace(tmp, PROMPT_MD)
    print("PROMPT_MD_BUMPED")
else:
    print("PROMPT_MD_NO_OLD_VER (already?)", f"has_new={('protocol_version = ' + NEW_VER) in pm}")

print("DONE")
