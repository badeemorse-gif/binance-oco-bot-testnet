# -*- coding: utf-8 -*-
"""rotate_state.py - \u0623\u062f\u0627\u0629 \u0627\u0644\u062a\u062f\u0648\u064a\u0631 \u0627\u0644\u062f\u0627\u0626\u0645\u0629 (\u0627\u0644\u0628\u0646\u062f 11.4 / \u0628\u0631\u0648\u062a\u0648\u0643\u0648\u0644 1.4).

\u0623\u062f\u0627\u0629 \u062b\u0627\u0628\u062a\u0629 \u0642\u0627\u0628\u0644\u0629 \u0644\u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0627\u0633\u062a\u062e\u062f\u0627\u0645 \u062a\u064f\u0624\u062a\u0645\u0650\u062a \u062a\u062f\u0648\u064a\u0631 hot/cold (\u0627\u0644\u0628\u0646\u062f 11.1):
\u062a\u0646\u0642\u0644 \u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u0625\u0644\u0649 state/\u060c \u0648\u062a\u064f\u0628\u0642\u064a \u0627\u0644\u0641\u0647\u0631\u0633 \u0627\u0644\u062d\u0627\u0631\u0651 \u0645\u064f\u0644\u062e\u0651\u0635\u064b\u0627 \u0645\u0639 ref+sha256\u060c
\u0643\u062a\u0627\u0628\u0629 \u0630\u0631\u0651\u064a\u0629 \u0645\u0639 \u0646\u0633\u062e\u0629 \u0642\u0627\u0628\u0644\u0629 \u0644\u0644\u0627\u0633\u062a\u0631\u062c\u0627\u0639 \u0641\u064a _archive\u060c \u062b\u0645 verify.

CLI:
  python tools/rotate_state.py verify
  python tools/rotate_state.py apply <ops.json>

\u0634\u0643\u0644 ops.json (\u0643\u0644 \u0627\u0644\u0645\u0641\u0627\u062a\u064a\u062d \u0627\u062e\u062a\u064a\u0627\u0631\u064a\u0629\u061b \u064a\u064f\u0633\u062a\u0628\u062f\u0644 "@NOW@" \u0628\u0637\u0627\u0628\u0639 \u0632\u0645\u0646\u064a UTC):
  {
    "backup_tag": "g1_39",
    "protocol_append": "<\u0646\u0635>",
    "set_last_updated": true,
    "defects":   [ {\u2026 \u0643\u0627\u0626\u0646 \u0628\u0646\u062f \u0643\u0627\u0645\u0644 \u2026} ],
    "decisions": [ {"id":"\u2026","decision":"\u2026"} ],
    "runlog":    [ {"ts":"@NOW@","actor":"executor","task":"\u2026","note":"\u2026"} ],
    "seals":     [ {"task":"\u2026","verified":true,\u2026} ],
    "working_memory": { \u2026 }
  }
"""
import json, os, sys, hashlib, shutil, tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS = os.path.join(ROOT, 'PROJECT_STATE.json')
WM = os.path.join(ROOT, 'WORKING_MEMORY.json')
ARCH = os.path.join(ROOT, '_archive')
STATE = os.path.join(ROOT, 'state')
DEFDIR = os.path.join(STATE, 'defects')
RUNLOG = os.path.join(STATE, 'run_log.jsonl')
DECLOG = os.path.join(STATE, 'decisions_log.json')
LEDGER = os.path.join(STATE, 'task_ledger.full.json')
MANIFEST = os.path.join(ARCH, 'manifest.json')


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _abs(ref):
    return os.path.join(ROOT, ref.replace('/', os.sep))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for ch in iter(lambda: f.read(65536), b''):
            h.update(ch)
    return 'sha256:' + h.hexdigest()


def _atomic(path, data_bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp'); os.close(fd)
    with open(tmp, 'wb') as f:
        f.write(data_bytes)
    os.replace(tmp, path)


def write_json_atomic(path, obj):
    _atomic(path, json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'))


def load_hot():
    with open(PS, encoding='utf-8') as f:
        return json.load(f)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------- mutation helpers (operate on hot dict + cold files) ----------

def add_defect(hot, obj):
    did = str(obj['id'])
    cold = os.path.join(DEFDIR, did + '.json')
    write_json_atomic(cold, obj)
    compact = {
        "id": obj.get('id'), "status": obj.get('status'), "title": obj.get('title'),
        "severity": obj.get('severity'), "ref": "state/defects/" + did + ".json",
        "detail_hash": sha256_file(cold),
    }
    dl = hot.setdefault('defect_log', [])
    for i, e in enumerate(dl):
        if e.get('id') == obj.get('id'):
            dl[i] = compact
            return
    dl.append(compact)


def append_runlog(hot, entry):
    lines = read_jsonl(RUNLOG)
    lines.append(entry)
    _atomic(RUNLOG, ('\n'.join(json.dumps(e, ensure_ascii=False) for e in lines) + '\n').encode('utf-8'))
    hot['run_log'] = lines[-3:]


def append_decision(hot, entry):
    lst = []
    if os.path.exists(DECLOG):
        with open(DECLOG, encoding='utf-8') as f:
            lst = json.load(f)
    lst.append(entry)
    write_json_atomic(DECLOG, lst)
    hot['decisions_log'] = lst[-3:]


def append_seal(hot, entry):
    hot.setdefault('completion_seals', []).append(entry)


def refresh_stores(hot):
    rl = read_jsonl(RUNLOG)
    hot['run_log_store'] = {"mode": "cold", "ref": "state/run_log.jsonl",
                            "hash": sha256_file(RUNLOG) if os.path.exists(RUNLOG) else None,
                            "count": len(rl)}
    dec = []
    if os.path.exists(DECLOG):
        with open(DECLOG, encoding='utf-8') as f:
            dec = json.load(f)
    hot['decisions_log_store'] = {"mode": "cold", "ref": "state/decisions_log.json",
                                  "hash": sha256_file(DECLOG) if os.path.exists(DECLOG) else None,
                                  "count": len(dec)}
    led = []
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding='utf-8') as f:
            led = json.load(f)
    hot['task_ledger_store'] = {"mode": "cold", "ref": "state/task_ledger.full.json",
                                "hash": sha256_file(LEDGER) if os.path.exists(LEDGER) else None,
                                "count": len(led)}


def backup(tag):
    os.makedirs(ARCH, exist_ok=True)
    man = load_manifest()
    for label, path in (('PROJECT_STATE', PS), ('WORKING_MEMORY', WM)):
        if os.path.exists(path):
            base = '%s.%s.json' % (label, tag)
            shutil.copyfile(path, os.path.join(ARCH, base))
            man.setdefault('entries', []).append({
                "file": base, "origin_path": os.path.basename(path),
                "task": tag, "reason": "pre-apply backup snapshot", "ts": now()})
    save_manifest(man)


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding='utf-8') as f:
            return json.load(f)
    return {"version": "1.4", "entries": []}


def save_manifest(man):
    write_json_atomic(MANIFEST, man)


def archive_file(path, task, reason):
    if not path:
        return False
    src = os.path.join(ROOT, path.replace('/', os.sep))
    if not os.path.exists(src):
        print('  archive skip (missing):', path)
        return False
    os.makedirs(ARCH, exist_ok=True)
    dest = os.path.join(ARCH, os.path.basename(src))
    os.replace(src, dest)
    man = load_manifest()
    man.setdefault('entries', []).append({
        "file": os.path.basename(src), "origin_path": path.replace('\\', '/'),
        "task": task, "reason": reason, "ts": now()})
    save_manifest(man)
    return True


# ---------- verify ----------

def verify():
    hot = load_hot()
    problems = []
    for e in hot.get('defect_log', []):
        ref = e.get('ref')
        if not ref or not os.path.exists(_abs(ref)):
            problems.append('defect %s: missing cold file %s' % (e.get('id'), ref)); continue
        if sha256_file(_abs(ref)) != e.get('detail_hash'):
            problems.append('defect %s: hash mismatch' % e.get('id'))
    for key, path, is_jsonl in [('run_log_store', RUNLOG, True),
                                ('decisions_log_store', DECLOG, False),
                                ('task_ledger_store', LEDGER, False)]:
        st = hot.get(key)
        if not st:
            problems.append('%s: missing in hot' % key); continue
        if not os.path.exists(path):
            problems.append('%s: missing cold %s' % (key, path)); continue
        if sha256_file(path) != st.get('hash'):
            problems.append('%s: hash mismatch' % key)
        cnt = len(read_jsonl(path)) if is_jsonl else len(json.load(open(path, encoding='utf-8')))
        if cnt != st.get('count'):
            problems.append('%s: count %d != store %s' % (key, cnt, st.get('count')))
    ok = not problems
    print('VERIFY', 'OK' if ok else 'FAIL',
          '| defects=%d run=%d dec=%d ledger=%d' % (
              len(hot.get('defect_log', [])),
              hot.get('run_log_store', {}).get('count'),
              hot.get('decisions_log_store', {}).get('count'),
              hot.get('task_ledger_store', {}).get('count')))
    print('  manifest_entries=%d' % len(load_manifest().get('entries', [])))
    for p in problems:
        print('  -', p)
    return ok


# ---------- apply ----------

def apply(ops_path):
    raw = open(ops_path, encoding='utf-8').read().replace('@NOW@', now())
    ops = json.loads(raw)
    backup(ops.get('backup_tag', 'rotate_' + now().replace(':', '').replace('-', '')))
    hot = load_hot()
    if ops.get('protocol_append'):
        hot['system_prompt'] = hot.get('system_prompt', '') + ops['protocol_append']
    for obj in ops.get('defects', []):
        add_defect(hot, obj)
    for e in ops.get('decisions', []):
        append_decision(hot, e)
    for e in ops.get('runlog', []):
        append_runlog(hot, e)
    for e in ops.get('seals', []):
        append_seal(hot, e)
    for a in ops.get('archive', []):
        archive_file(a.get('path'), a.get('task') or ops.get('task'), a.get('reason'))
    if ops.get('set_last_updated'):
        hot['last_updated'] = now()
    refresh_stores(hot)
    write_json_atomic(PS, hot)
    if 'working_memory' in ops:
        write_json_atomic(WM, ops['working_memory'])
    ok = verify()
    print('APPLY', 'OK' if ok else 'FAIL', '| hot_bytes=%d' % os.path.getsize(PS))
    return ok


def main(argv):
    if len(argv) >= 2 and argv[1] == 'verify':
        return 0 if verify() else 1
    if len(argv) >= 3 and argv[1] == 'apply':
        return 0 if apply(argv[2]) else 1
    if len(argv) >= 5 and argv[1] == 'archive':
        ok = archive_file(argv[2], argv[3], ' '.join(argv[4:]))
        print('ARCHIVED' if ok else 'ARCHIVE_SKIPPED', argv[2])
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
