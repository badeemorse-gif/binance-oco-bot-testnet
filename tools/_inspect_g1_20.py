# -*- coding: utf-8 -*-
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

d = json.load(open('PROJECT_STATE.json', encoding='utf-8'))
dl = d['defect_log']
print('DEFECT_LOG_TYPE', type(dl).__name__)
print('ROOT_KEYS', list(d.keys()))

e = None
if isinstance(dl, dict):
    print('LOG_LAST_KEYS', list(dl.keys())[-6:])
    e = dl.get('G1.20')
else:
    print('LOG_LAST_IDS', [it.get('id') for it in dl if isinstance(it, dict)][-6:])
    for it in dl:
        if isinstance(it, dict) and it.get('id') == 'G1.20':
            e = it
            break

print('===G1.20_ENTRY===')
print(json.dumps(e, ensure_ascii=False, indent=2))

print('===WORKING_MEMORY_CURRENT===')
try:
    wm = json.load(open('WORKING_MEMORY.json', encoding='utf-8'))
    print('WM_KEYS', list(wm.keys()) if isinstance(wm, dict) else type(wm).__name__)
    print(json.dumps(wm, ensure_ascii=False, indent=2))
except Exception as ex:
    print('WM_ERR', ex)
