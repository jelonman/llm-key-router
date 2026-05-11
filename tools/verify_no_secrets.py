#!/usr/bin/env python3
from pathlib import Path
import re, sys
ROOT=Path(__file__).resolve().parents[1]
SKIP_NAMES={"secrets.env",".env"}; SKIP_PARTS={"state",".git","__pycache__","dist","build",".pytest_cache"}
PATS=[re.compile(r"sk-or-v1-[A-Za-z0-9_\-]{20,}"), re.compile(r"(?i)OPENROUTER_[A-Z0-9_]*KEY\s*=\s*sk-or-v1-[A-Za-z0-9_\-]{20,}"), re.compile(r"(?i)OLLAMA_[A-Z0-9_]*KEY\s*=\s*[A-Za-z0-9_\-]{20,}")]
hits=[]
for p in ROOT.rglob('*'):
    if not p.is_file(): continue
    rel=p.relative_to(ROOT)
    if p.name in SKIP_NAMES or any(part in SKIP_PARTS for part in rel.parts): continue
    try: text=p.read_text(encoding='utf-8')
    except UnicodeDecodeError: continue
    for pat in PATS:
        for m in pat.finditer(text): hits.append((str(rel), m.group(0)[:24]+'...'))
if hits:
    print('SECRET-LIKE STRINGS FOUND')
    for rel,s in hits: print(f'{rel}: {s}')
    sys.exit(1)
print('OK: no secret-like strings found')
