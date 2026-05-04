# CFO Bridge — Paperclip → Dashboard

Source-of-truth flow for finance data. CFO agent in Paperclip uses these tools to update `data/finance.json`, which dashboard reads on every refresh.

## Files

- `update.py` — apply JSON patch to `data/finance.json` (deep merge)
- `add-tx.py` — append transaction to `data/finance.json#/ledger`
- `notify.py` — append event to `data/cfo-events.jsonl` (TG bot polls this)
- `sync.sh` — git add + commit + push (single command for CFO to call after changes)

## CFO agent skill registration (Paperclip)

Tell the CFO agent these shell commands:

```bash
# Update top-level field
python3 ~/zinin-corp-dashboard/tools/cfo/update.py \
  --field kpis.mrr.current_cents --value 120000

# Add transaction (most common)
python3 ~/zinin-corp-dashboard/tools/cfo/add-tx.py \
  --date 2026-05-04 --icon leaf --desc "Botanica · 2 users" --cat Revenue --cents 10000

# Notify Tim with finance event
python3 ~/zinin-corp-dashboard/tools/cfo/notify.py \
  --level warn --title "MRR drop" --text "Botanica churned 1 user — MRR -$50"

# Push everything to GitHub (VPS pulls every 5 min)
~/zinin-corp-dashboard/tools/cfo/sync.sh "CFO: MRR update + 2 transactions"
```

## Schema (data/finance.json)

See `~/zinin-corp-dashboard/data/finance.json` — `_meta`, `net_position`, `cash_sources`, `kpis`, `pnl_monthly`, `ledger`, `spend_by_category`, `anomalies`, `forecast`, `coming_up_30d`.

All money in cents (integer). All dates ISO-8601.

## Sync to VPS

VPS cron pulls `/opt/ai-corp-dashboards/data/*.json` from GitHub every 5 minutes. To bypass and force immediate sync:

```bash
ssh root@185.202.239.165 'cd /opt/ai-corp-dashboards && git pull && ls data/'
```
