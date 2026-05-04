#!/usr/bin/env python3
"""CFO add transaction — append entry to data/finance.json#/ledger (most-recent-first).

Usage:
  add-tx.py --date 2026-05-04 --icon leaf --desc "Botanica · 2 users" --cat Revenue --cents 10000
  add-tx.py --date 2026-05-04 --icon server --desc "Contabo VPS" --cat Infra --cents -3200
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / 'data' / 'finance.json'

VALID_CATS = {'Revenue', 'LLM', 'Infra', 'SaaS', 'Domains/CDN', 'Image/video', 'Media', 'Other'}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--date', required=True, help='YYYY-MM-DD')
    p.add_argument('--icon', default='circle-dollar-sign', help='Lucide icon name')
    p.add_argument('--desc', required=True)
    p.add_argument('--cat', required=True, help=f'One of: {", ".join(sorted(VALID_CATS))}')
    p.add_argument('--cents', type=int, required=True, help='Positive=in, negative=out')
    p.add_argument('--max-rows', type=int, default=30, help='Trim ledger to last N entries')
    args = p.parse_args()

    if args.cat not in VALID_CATS:
        print(f'[add-tx] WARN unknown category "{args.cat}" — using as-is', file=sys.stderr)

    data = json.loads(FIN.read_text(encoding='utf-8'))
    data.setdefault('ledger', []).insert(0, {
        'date': args.date,
        'icon': args.icon,
        'desc': args.desc,
        'cat': args.cat,
        'amount_cents': args.cents,
    })
    if args.max_rows and len(data['ledger']) > args.max_rows:
        data['ledger'] = data['ledger'][:args.max_rows]
    data.setdefault('_meta', {})['updated_at'] = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

    FIN.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'[add-tx] +1 entry · ledger length={len(data["ledger"])}')

if __name__ == '__main__':
    main()
