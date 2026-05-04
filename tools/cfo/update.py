#!/usr/bin/env python3
"""CFO update — apply field patch to data/finance.json (deep merge).

Usage:
  update.py --field kpis.mrr.current_cents --value 120000
  update.py --field anomalies --value '[{"id":"a1","level":"warn","title":"X","text":"Y"}]' --json
  update.py --merge '{"kpis":{"mrr":{"current_cents":120000}}}'
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / 'data' / 'finance.json'

def deep_merge(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        for k, v in patch.items():
            base[k] = deep_merge(base.get(k), v) if k in base else v
        return base
    return patch

def set_path(data, path, value):
    keys = path.split('.')
    cur = data
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--field', help='Dotted path, e.g. kpis.mrr.current_cents')
    p.add_argument('--value', help='New value (string by default)')
    p.add_argument('--json', action='store_true', help='Parse --value as JSON')
    p.add_argument('--merge', help='JSON object to deep-merge into root')
    p.add_argument('--int', action='store_true', help='Cast --value to int')
    p.add_argument('--float', action='store_true', help='Cast --value to float')
    args = p.parse_args()

    if not FIN.exists():
        sys.exit(f'[update] {FIN} missing')
    data = json.loads(FIN.read_text(encoding='utf-8'))

    if args.merge:
        deep_merge(data, json.loads(args.merge))
    elif args.field is not None:
        if args.value is None:
            sys.exit('[update] --field requires --value')
        v = args.value
        if args.json:   v = json.loads(v)
        elif args.int:  v = int(v)
        elif args.float:v = float(v)
        set_path(data, args.field, v)
    else:
        sys.exit('[update] need --field/--value or --merge')

    data.setdefault('_meta', {})['updated_at'] = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    FIN.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'[update] OK · {args.field or args.merge[:60]}')

if __name__ == '__main__':
    main()
