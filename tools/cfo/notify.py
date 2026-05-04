#!/usr/bin/env python3
"""CFO notify — append event to data/cfo-events.jsonl. TG bot polls this file
and forwards new events to Tim's Saved Messages.

Usage:
  notify.py --level info  --title "Monthly close"  --text "March 2026 closed: $825 net"
  notify.py --level warn  --title "MRR drop"       --text "Botanica -1 user"
  notify.py --level critical --title "Cash <$500" --text "Top up TBC"
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / 'data' / 'cfo-events.jsonl'

LEVELS = {'info', 'warn', 'critical'}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--level', required=True, choices=sorted(LEVELS))
    p.add_argument('--title', required=True)
    p.add_argument('--text',  required=True)
    p.add_argument('--actor', default='cfo')
    args = p.parse_args()

    EVENTS.parent.mkdir(exist_ok=True)
    event = {
        'ts': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
        'actor': args.actor,
        'level': args.level,
        'title': args.title,
        'text':  args.text,
    }
    with EVENTS.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
    print(f'[notify] {args.level.upper()} · {args.title}')

if __name__ == '__main__':
    main()
