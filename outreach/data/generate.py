#!/usr/bin/env python3
"""Generate dashboard JSON from live sources.

Sources:
  - Twenty CRM REST (~/.secrets/twenty.env)         → opportunities, stages, replies
  - SuperJob replies-state.json                      → invitations / rejections
  - outreach-hunt logs/send-{date}.md                → today's send list (Avito)
  - outreach-hunt state/send-count-{date}.json       → daily counters
  - superjob-outreach-data/sent.json                 → SJ sent history

Run:
  python3 ~/zinin-corp-dashboard/outreach/data/generate.py

Output:
  ~/zinin-corp-dashboard/outreach/data/stats.json
  ~/zinin-corp-dashboard/outreach/data/agents.json
  ~/zinin-corp-dashboard/outreach/data/events-recent.json

Best-effort: missing sources are skipped silently with `[gen] WARN` to stderr.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOME = Path.home()
DASH_DIR = HOME / "zinin-corp-dashboard" / "outreach" / "data"
DASH_DIR.mkdir(parents=True, exist_ok=True)

PLATFORM_LABELS = {
    "AVITO_RABOTA": ("avito_rabota", "Avito Работа", "avito", 20),
    "SUPERJOB":     ("superjob",     "SuperJob",     "sj",    30),
    "GULFTALENT":   ("gulftalent",   "GulfTalent",   "gt",    15),
    "HH":           ("hh",           "HeadHunter",   "hh",    50),
    "KARIYER":      ("kariyer",      "Kariyer.net",  "kar",   30),
    "HABR":         ("habr",         "Habr Career",  "habr",  20),
}

# ─── Twenty client ────────────────────────────────────────────────────────────
def load_twenty():
    f = HOME / ".secrets" / "twenty.env"
    if not f.is_file():
        print("[gen] WARN twenty.env not found", file=sys.stderr)
        return None, None
    api_url = api_key = None
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == "TWENTY_API_URL": api_url = v.strip()
        elif k.strip() == "TWENTY_API_KEY": api_key = v.strip()
    return api_url, api_key

def twenty_get(url, key, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params, safe="[]:")
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except Exception as e:
        return 0, {"error": str(e)}

def pull_opportunities():
    api_url, key = load_twenty()
    if not api_url:
        return {}
    by_source = {}
    for source in PLATFORM_LABELS.keys():
        code, body = twenty_get(
            f"{api_url}/rest/opportunities",
            key,
            {"filter": f"source[eq]:{source}", "limit": "100", "order_by": "createdAt[DescNullsLast]"},
        )
        if code == 200:
            arr = (body.get("data") or {}).get("opportunities") or []
            by_source[source] = arr
    return by_source

# ─── Lead pipeline classification ─────────────────────────────────────────────
def classify_lead(opp, now):
    """Return one of:
       sent_waiting     — sent, no reply, < 72h
       no_reaction      — sent, no reply, > 72h (cold)
       hr_invite        — HR invited us proactively (Twenty stage MEETING, no replyReceivedAt)
       interested       — they replied positively (Twenty stage MEETING + replyReceivedAt set).
                          NOT actually a booked meeting yet — just "interest expressed"
       proposal_sent    — we sent commercial offer (Twenty stage PROPOSAL)
       declined         — they refused (Twenty stage NOT_NOW)
       won              — closed deal (Twenty stage CUSTOMER)
    """
    stage = opp.get("stage") or "SCREENING"
    if stage == "CUSTOMER":  return "won"
    if stage == "NOT_NOW":   return "declined"
    if stage == "PROPOSAL":  return "proposal_sent"
    reply_at = opp.get("replyReceivedAt")
    if stage == "MEETING":
        return "interested" if reply_at else "hr_invite"
    # SCREENING
    if reply_at:
        return "replied_neutral"
    created = opp.get("createdAt") or ""
    if not created:
        return "sent_waiting"
    try:
        cdt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_h = (now - cdt).total_seconds() / 3600
        return "sent_waiting" if age_h < 72 else "no_reaction"
    except Exception:
        return "sent_waiting"

def compute_lead_pipeline(opps_by_source):
    pipeline = {
        "sent_waiting": 0, "no_reaction": 0, "replied_neutral": 0,
        "hr_invite": 0, "interested": 0, "proposal_sent": 0,
        "declined": 0, "won": 0,
    }
    now = datetime.now(timezone.utc)
    for source, arr in opps_by_source.items():
        for o in arr:
            pipeline[classify_lead(o, now)] += 1
    return pipeline

# ─── Stats builder ────────────────────────────────────────────────────────────
def build_stats(opps):
    today = datetime.now().strftime("%Y-%m-%d")
    today_iso_prefix = today  # Twenty createdAt format: 2026-05-05T...
    by_platform = {}
    totals = {"sent": 0, "replies": 0, "hot": 0, "errors": 0}
    funnel = {"scanned": 0, "filtered": 0, "sent": 0, "replied": 0, "hot": 0, "meeting": 0}
    twenty_stages = {"SCREENING": 0, "MEETING": 0, "PROPOSAL": 0, "NOT_NOW": 0, "CUSTOMER": 0, "REMIND": 0}

    now = datetime.now(timezone.utc)

    for source, arr in opps.items():
        if source not in PLATFORM_LABELS:
            continue
        key, label, short, qmax = PLATFORM_LABELS[source]
        sent_total = len(arr)
        sent_today = sum(1 for o in arr if (o.get("createdAt") or "").startswith(today_iso_prefix))
        replies = sum(1 for o in arr if o.get("replyReceivedAt"))
        invited = sum(1 for o in arr if classify_lead(o, now) == "hr_invite")
        meeting = sum(1 for o in arr if classify_lead(o, now) == "interested")
        hot = invited + meeting
        # last action ts
        sorted_arr = sorted(arr, key=lambda o: o.get("lastTouchAt") or o.get("createdAt") or "", reverse=True)
        last_ts = ""
        if sorted_arr:
            t = sorted_arr[0].get("lastTouchAt") or sorted_arr[0].get("createdAt") or ""
            last_ts = t[11:19] if len(t) >= 19 else ""

        by_platform[key] = {
            "label": label, "short": short,
            "sent": sent_today,
            "sent_total": sent_total,
            "replies": replies,
            "hot": hot,
            "errors": 0,
            "daily_quota_used": sent_today,
            "daily_quota_max": qmax,
            "last_action_ts": last_ts,
            "status": "idle",
            "lead_pipeline": {
                "sent_waiting":   sum(1 for o in arr if classify_lead(o, now) == "sent_waiting"),
                "no_reaction":    sum(1 for o in arr if classify_lead(o, now) == "no_reaction"),
                "replied_neutral":sum(1 for o in arr if classify_lead(o, now) == "replied_neutral"),
                "hr_invite":      sum(1 for o in arr if classify_lead(o, now) == "hr_invite"),
                "interested":     sum(1 for o in arr if classify_lead(o, now) == "interested"),
                "proposal_sent":  sum(1 for o in arr if classify_lead(o, now) == "proposal_sent"),
                "declined":       sum(1 for o in arr if classify_lead(o, now) == "declined"),
                "won":            sum(1 for o in arr if classify_lead(o, now) == "won"),
            },
        }

        totals["sent"]    += sent_today
        totals["replies"] += replies
        totals["hot"]     += hot
        funnel["sent"]    += sent_today
        funnel["replied"] += replies
        funnel["hot"]     += hot

        for o in arr:
            stage = o.get("stage") or "SCREENING"
            twenty_stages[stage] = twenty_stages.get(stage, 0) + 1

    funnel["meeting"] = twenty_stages.get("MEETING", 0) + twenty_stages.get("PROPOSAL", 0)
    total_opps = sum(len(arr) for arr in opps.values())

    return {
        "date": today,
        "generated_at": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "totals_today": totals,
        "by_platform": by_platform,
        "twenty": {
            "opportunities_total": total_opps,
            "by_stage": twenty_stages,
        },
        "funnel": funnel,
        "lead_pipeline": compute_lead_pipeline(opps),
    }

# ─── Events ───────────────────────────────────────────────────────────────────
def opp_to_events(opps, days_back=2):
    """Reconstruct event timeline from Opportunity timestamps.

    Only emits events from `days_back` last days (default 2: today + yesterday).
    Older Opportunities still count toward stats/lead_pipeline but don't pollute
    the live log. Each Opportunity yields:
      - send_done  at createdAt
      - reply_received at replyReceivedAt (if set)

    Adds `_date` (YYYY-MM-DD) and `_is_today` to each event. Frontend shows
    only HH:MM:SS for today, prefixes "Mon DD " for older.
    """
    events = []
    now = datetime.now(timezone.utc)
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = now - timedelta(days=days_back)

    def _evt_date(iso_ts):
        if not iso_ts: return ""
        return iso_ts[:10]

    def _evt_ts(iso_ts):
        """Return display ts. Today → 'HH:MM:SS'. Older → 'Mon DD HH:MM'."""
        if not iso_ts or len(iso_ts) < 19: return ""
        date_part = iso_ts[:10]
        time_part = iso_ts[11:19]
        if date_part == today:
            return time_part
        # Older: "May 04 22:32" style
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            return dt.strftime("%b %d %H:%M")
        except Exception:
            return f"{date_part[5:]} {time_part[:5]}"

    for source, arr in opps.items():
        if source not in PLATFORM_LABELS:
            continue
        key, label, short, _qmax = PLATFORM_LABELS[source]
        for o in arr:
            name = o.get("name") or "?"
            url = o.get("sourceUrl") or ""
            opp_id = o.get("id")
            lead_st = classify_lead(o, now)
            created = o.get("createdAt") or ""
            if created:
                try:
                    cdt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if cdt < cutoff:
                        continue  # old event — skip log but counts in stats
                except Exception:
                    pass
                events.append({
                    "ts": _evt_ts(created),
                    "_sort": created,
                    "_date": _evt_date(created),
                    "_is_today": _evt_date(created) == today,
                    "level": "OK",
                    "platform": key,
                    "agent": f"outreach-{key.split('_')[0]}",
                    "type": "send_done",
                    "lead_status": lead_st,
                    "message": name,
                    "meta": {"opp_id": opp_id, "url": url},
                })
            reply_at = o.get("replyReceivedAt")
            if reply_at:
                try:
                    rdt = datetime.fromisoformat(reply_at.replace("Z", "+00:00"))
                    if rdt < cutoff:
                        continue
                except Exception:
                    pass
                stage = o.get("stage")
                lvl = "HOT" if stage == "MEETING" else "WARN" if stage == "NOT_NOW" else "INFO"
                msg_pref = {"MEETING": "Invited / interest", "NOT_NOW": "Declined", "PROPOSAL": "Proposal sent"}.get(stage, "Reply received")
                events.append({
                    "ts": _evt_ts(reply_at),
                    "_sort": reply_at,
                    "_date": _evt_date(reply_at),
                    "_is_today": _evt_date(reply_at) == today,
                    "level": lvl,
                    "platform": key,
                    "agent": "system",
                    "type": "reply_received",
                    "lead_status": lead_st,
                    "message": f"{msg_pref} · {name}",
                    "meta": {"opp_id": opp_id, "stage": stage},
                })
    events.sort(key=lambda e: e.get("_sort") or "", reverse=False)
    for e in events:
        e.pop("_sort", None)
    return events[-200:]

# ─── SJ replies-state additions ───────────────────────────────────────────────
def fetch_sj_thread_bodies():
    """Pull full message bodies for invited threads via SJ API. Returns dict
    {firm_name: {body, contact, date_sent}}. Best-effort — empty dict on failure."""
    sj_root = HOME / "superjob-outreach"
    scripts = sj_root / "scripts"
    if not scripts.is_dir():
        return {}
    try:
        sys.path.insert(0, str(scripts))
        import sj_api  # type: ignore
        creds = sj_api.load_credentials()
        r = sj_api.get("/messages/list/", creds=creds)
        out = {}
        for t in r.body.get("objects", []):
            firm = t.get("firm_name")
            if not firm: continue
            out[firm] = {
                "body": (t.get("body") or "").strip(),
                "date_sent": t.get("date_sent"),
                "thread_id": t.get("id") or t.get("mailId"),
                "status_text": t.get("status_text"),
            }
        return out
    except Exception as _e:
        print(f"[gen] WARN fetch_sj_thread_bodies: {_e}", file=sys.stderr)
        return {}

def sj_replies_events():
    f = HOME / "superjob-outreach-data" / "replies-state.json"
    if not f.is_file():
        return []
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    threads = d.get("threads", [])
    bodies = fetch_sj_thread_bodies()
    out = []
    for t in threads:
        cls = t.get("classification")
        if cls != "waiting_my_reply":
            continue
        firm = t.get("firm_name") or "?"
        body_info = bodies.get(firm, {})
        body = body_info.get("body", "")
        date_sent = t.get("date_sent")
        if isinstance(date_sent, (int, float)) and date_sent > 0:
            ts = datetime.fromtimestamp(date_sent, tz=timezone.utc).astimezone().strftime("%H:%M:%S")
            sort = datetime.fromtimestamp(date_sent, tz=timezone.utc).isoformat()
        else:
            ts = "00:00:00"; sort = ""
        # First line of body for compact preview, full body in meta
        body_preview = body.split("\n")[0][:150] if body else "(invitation)"
        out.append({
            "ts": ts,
            "_sort": sort,
            "level": "INFO",
            "platform": "superjob",
            "agent": "outreach-superjob",
            "type": "invitation_received",
            "lead_status": "invited",
            "message": f"{firm} · {body_preview}",
            "meta": {
                "thread_id": t.get("thread_id"),
                "status_text": t.get("status_text"),
                "firm": firm,
                "body": body,
                "date_sent": date_sent,
            },
        })
    out.sort(key=lambda e: e.get("_sort") or "", reverse=False)
    for e in out: e.pop("_sort", None)
    return out

# ─── Manual conversation injections (Avito doesn't expose easy API) ──────────
def manual_conversations():
    """Hand-curated reply texts that aren't in Twenty Opportunities (Avito DM
    doesn't expose API). Updated when new replies come in."""
    return [
        {
            "ts": "13:35:00",
            "level": "WARN",
            "platform": "avito_rabota",
            "agent": "outreach-avito",
            "type": "reply_received",
            "lead_status": "declined",
            "message": "Черника · «Посмотрите похожие вакансии — среди них может найтись подходящая»",
            "meta": {
                "company": "Черника",
                "vacancy": "Маркетолог / Контент-продюсер (HoReCa)",
                "salary": "80–120k₽",
                "body": "Посмотрите похожие вакансии — среди них может найтись подходящая.",
                "classification": "soft_decline",
            },
        },
        {
            "ts": "14:12:00",
            "level": "HOT",
            "platform": "avito_rabota",
            "agent": "outreach-avito",
            "type": "reply_received",
            "lead_status": "invited",
            "message": "PGM · «Интересно. Можно обсудить»",
            "meta": {
                "company": "PGM",
                "vacancy": "Смм специалист, маркетолог",
                "body": "Интересно. Можно обсудить",
                "classification": "interest",
                "stage_to": "MEETING",
            },
        },
        {
            "ts": "14:41:47",
            "level": "OK",
            "platform": "avito_rabota",
            "agent": "manual",
            "type": "reply_sent",
            "lead_status": "meeting",
            "message": "PGM · отправлен Calendly + AI-services pivot",
            "meta": {
                "company": "PGM",
                "body": ("Спасибо за быстрый ответ! Удобно созвониться 30 минут — посмотрим ваши задачи "
                         "и какую часть SMM можно перевести на AI-агентов. Слот: https://calendly.com/timzinin\n\n"
                         "Если перепиской удобнее — расскажите коротко, что сейчас руками делает специалист "
                         "(контент, постинг, креативы, аналитика). Пришлю кейсы под ваш стек.\n\n"
                         "Тим"),
                "template": "pgm_v1_calendly",
            },
        },
        {
            "ts": "14:46:36",
            "level": "OK",
            "platform": "superjob",
            "agent": "manual",
            "type": "reply_sent",
            "lead_status": "meeting",
            "message": "АВС Рус · pivot на AI-services + Calendly",
            "meta": {
                "company": "АВС Рус",
                "body": ("Александр, спасибо за приглашение! Уточню по своей стороне: я фокусируюсь на консалтинге "
                         "AI-интеграции в маркетинговые процессы (ИП, удалённо), а не на штатной позиции менеджера. "
                         "Если у АВС Рус есть задача внедрить AI-агентов в работу с маркетплейсами или в маркетинг "
                         "(контент, аналитика, ассортимент) — давайте 30 минут созвонимся: https://calendly.com/timzinin\n\n"
                         "Если вакансия требует именно штатного менеджера — спасибо, тогда не подойду по формату.\n"
                         "Тим Зинин"),
                "template": "sj_avs_v1_pivot",
            },
        },
    ]

# ─── Agents (minimal: no live tracking yet, just placeholder) ─────────────────
def build_agents():
    """Return current agents. Until agents start writing heartbeats themselves,
    this returns []. In live mode, agents will append to ./agents.json."""
    f = DASH_DIR / "agents.json"
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

# ─── events.jsonl loader (source-of-truth for ops journal) ────────────────────
EVENTS_DIR = HOME / "outreach-hunt" / "state" / "events"

# Map our taxonomy → dashboard event-types and severity levels.
_EVENT_LEVEL = {
    "send_ok":         "OK",
    "send_attempt":    "INFO",
    "send_fail":       "ERR",
    "send_skipped":    "INFO",
    "reply_received":  "INFO",   # adjusted below by intent
    "reply_intent":    "INFO",
    "pending_outbox":  "HOT",    # action required: reply with Calendly
    "twenty_sync_ok":  "INFO",
    "twenty_sync_fail":"WARN",
    "scan_started":    "INFO",
    "scan_done":       "INFO",
    "vacancy_kept":    "INFO",
    "vacancy_dropped": "INFO",
    "blacklist_drop":  "WARN",
    "throttle_wait":   "INFO",
    "agent_idle":      "INFO",
    "agent_error":     "ERR",
}

def _agent_to_platform_key(agent: str, board: str) -> str:
    """Resolve dashboard platform key from event agent/board."""
    a = (agent or "").lower()
    b = (board or "").lower()
    if "avito" in (a + b): return "avito_rabota" if "uslugi" not in b else "avito_uslugi"
    if "superjob" in (a + b): return "superjob"
    if "gulftalent" in (a + b): return "gulftalent"
    if "habr" in (a + b): return "habr"
    if "kariyer" in (a + b): return "kariyer"
    if "hh" in (a + b): return "hh"
    return a or "unknown"

def load_events_jsonl(days_back: int = 1):
    """Read events from events-YYYY-MM-DD.jsonl (last `days_back` days incl. today).
    Returns list of dashboard-shaped events ready to merge with opp_to_events()."""
    out = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_local = datetime.now().strftime("%Y-%m-%d")
    if not EVENTS_DIR.is_dir():
        return out
    for off in range(days_back + 1):
        d = (datetime.now(timezone.utc) - timedelta(days=off)).strftime("%Y-%m-%d")
        f = EVENTS_DIR / f"events-{d}.jsonl"
        if not f.is_file():
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts = e.get("ts") or ""
                date_part = ts[:10]
                time_part = ts[11:19]
                etype = e.get("type") or "unknown"
                level = _EVENT_LEVEL.get(etype, "INFO")
                # Hot leads: reply with intent=interest
                if etype == "reply_received":
                    intent = (e.get("data") or {}).get("intent") or ""
                    if intent in ("interest", "clarify_pricing"):
                        level = "HOT"
                    elif intent == "decline":
                        level = "WARN"
                pkey = _agent_to_platform_key(e.get("agent",""), e.get("board",""))
                # Display label for log feed
                co = e.get("company") or ""
                ti = e.get("title") or ""
                msg = co
                if ti and ti != co:
                    msg = f"{co} · {ti}" if co else ti
                if not msg:
                    msg = etype
                # Add intent / data hint to message for richer log
                d_data = e.get("data") or {}
                if etype == "reply_received":
                    intent = d_data.get("intent") or "?"
                    body = d_data.get("body_preview") or d_data.get("status_text") or ""
                    msg = f"[{intent}] {co}" + (f": {body[:80]}" if body else "")
                if etype == "send_fail":
                    err = d_data.get("error_message") or d_data.get("error") or "?"
                    msg = f"{msg} · {str(err)[:60]}"
                if etype == "pending_outbox":
                    bp = d_data.get("body_preview") or ""
                    msg = f"⚡ ОТВЕТЬ → {co}" + (f" · {bp[:60]}" if bp else "")
                if date_part == today_local:
                    disp_ts = time_part
                else:
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
                        disp_ts = dt.strftime("%b %d %H:%M")
                    except Exception:
                        disp_ts = f"{date_part[5:]} {time_part[:5]}"
                out.append({
                    "ts": disp_ts,
                    "_sort": ts,
                    "_date": date_part,
                    "_is_today": date_part == today_local,
                    "level": level,
                    "platform": pkey,
                    "agent": f"outreach-{(e.get('agent') or '?').split('-')[0]}",
                    "type": etype,
                    "message": msg,
                    "meta": {
                        "opp_id": e.get("opp_id"),
                        "vacancy_id": e.get("vacancy_id"),
                        "url": e.get("url"),
                        **({"intent": d_data.get("intent")} if etype == "reply_received" else {}),
                    },
                })
        except Exception as exc:
            print(f"[gen] WARN events.jsonl read failed: {exc}", file=sys.stderr)
    return out

def build_agents_from_events(events, opps):
    """Build per-agent live cards from events + Twenty opportunities.

    Each agent card includes:
      - agent_id ("outreach-avito"), platform key, label
      - sent_today (events send_ok)
      - replies_today (events reply_received)
      - errors_today (events send_fail / agent_error)
      - last_action (most recent event ts, type, message)
      - status: "active" if any event in last 30min, else "idle"
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cards = {}
    for e in events:
        sort_ts = e.get("_sort") or ""
        if not sort_ts.startswith(today_iso):
            continue
        pkey = e.get("platform") or "unknown"
        if pkey not in {v[0] for v in PLATFORM_LABELS.values()}:
            continue
        c = cards.setdefault(pkey, {
            "platform": pkey,
            "agent_id": e.get("agent") or f"outreach-{pkey.split('_')[0]}",
            "sent_today": 0, "replies_today": 0, "errors_today": 0,
            "last_event_ts": "", "last_event_type": "", "last_event_message": "",
        })
        et = e.get("type")
        if et == "send_ok": c["sent_today"] += 1
        elif et == "reply_received": c["replies_today"] += 1
        elif et in ("send_fail","agent_error","twenty_sync_fail"): c["errors_today"] += 1
        if sort_ts > c["last_event_ts"]:
            c["last_event_ts"] = sort_ts
            c["last_event_type"] = et or ""
            c["last_event_message"] = e.get("message") or ""
    # Add cards for sources without events yet (from PLATFORM_LABELS)
    for src, (pkey, label, short, qmax) in PLATFORM_LABELS.items():
        if pkey not in cards:
            cards[pkey] = {
                "platform": pkey,
                "agent_id": f"outreach-{pkey.split('_')[0]}",
                "sent_today": 0, "replies_today": 0, "errors_today": 0,
                "last_event_ts": "", "last_event_type": "", "last_event_message": "",
            }
        cards[pkey]["label"] = label
        cards[pkey]["short"] = short
        cards[pkey]["quota_max"] = qmax
        # Status: active if event in last 30min
        last = cards[pkey]["last_event_ts"]
        cards[pkey]["status"] = "active" if (last and (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z","+00:00"))).total_seconds() < 1800) else "idle"
    return list(cards.values())

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("[gen] generating dashboard data...", file=sys.stderr)
    opps = pull_opportunities()
    if not opps:
        print("[gen] WARN no opportunities pulled (Twenty unreachable?)", file=sys.stderr)

    stats = build_stats(opps)
    events_opps = opp_to_events(opps)
    events_sj = sj_replies_events()
    events_manual = manual_conversations()
    events_jsonl = load_events_jsonl(days_back=1)  # primary live ops journal

    # Merge sources. Sort by raw ISO `_sort` if present (events_jsonl has it),
    # otherwise by `ts` (legacy display string — same prefix order for today).
    events = events_opps + events_sj + events_manual + events_jsonl
    events.sort(key=lambda e: (e.get("_sort") or e.get("ts") or ""))
    events = events[-400:]

    # conversations.json — only inbound + auto-replies, full body
    convs = [e for e in events if e.get("type") in ("reply_received", "reply_sent", "invitation_received")]
    convs_path = DASH_DIR / "conversations.json"
    convs_path.write_text(json.dumps(convs[-30:], ensure_ascii=False, indent=2), encoding="utf-8")

    # Build per-agent cards BEFORE stripping _sort (it relies on raw ISO ts).
    agents = build_agents_from_events(events_jsonl, opps)

    # Strip helper keys from output (frontend doesn't need them)
    for e in events:
        e.pop("_sort", None)

    # Write atomically
    for fname, data in [("stats.json", stats), ("agents.json", agents), ("events-recent.json", events)]:
        target = DASH_DIR / fname
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    print(f"[gen] OK", file=sys.stderr)
    print(f"  totals: {stats['totals_today']}", file=sys.stderr)
    print(f"  pipeline: {stats['lead_pipeline']}", file=sys.stderr)
    print(f"  events: {len(events)}", file=sys.stderr)
    print(f"  → {DASH_DIR}", file=sys.stderr)

if __name__ == "__main__":
    main()
