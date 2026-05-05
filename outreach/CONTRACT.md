# Outreach Ops Dashboard — Data Contract

> **Single source of truth** для любого outreach-агента (Avito, SuperJob, GulfTalent, HH, Kariyer, Habr, Workspace, etc.). Чтобы агент попал в дашборд — пишет в эти файлы по схеме ниже. Дашборд polls 5s.

## Где лежат файлы

Локально (Mac):
- `~/zinin-corp-dashboard/outreach/data/stats.json`
- `~/zinin-corp-dashboard/outreach/data/agents.json`
- `~/zinin-corp-dashboard/outreach/data/events-recent.json`
- `~/zinin-corp-dashboard/outreach/data/events.jsonl` *(append-only audit log; не читается дашбордом, читается events-recent.json которое его hot-tail последних 200 строк)*

На сервере (Contabo VPS 30, прод):
- `/opt/ai-corp-dashboards/outreach/data/*.json`
- nginx serves `https://corp.timzinin.com/outreach/?key=outreach_ops_2026`

## stats.json

```json
{
  "date": "2026-05-05",
  "totals_today": { "sent": 16, "replies": 8, "hot": 2, "errors": 1 },
  "by_platform": {
    "<platform_key>": {
      "label": "Avito Работа",      // human-readable name in card title
      "short": "avito",              // 3-5 char tag for log feed
      "sent": 14,
      "replies": 2,
      "hot": 1,
      "errors": 0,
      "daily_quota_used": 14,
      "daily_quota_max": 20,
      "last_action_ts": "15:00:01",  // HH:MM:SS local time
      "status": "running"            // running | idle | error | warn
    }
  },
  "twenty": {
    "opportunities_total": 1004,
    "by_stage": { "SCREENING": 14, "MEETING": 2, "PROPOSAL": 0, "NOT_NOW": 8 }
  },
  "funnel": {
    "scanned": 471, "filtered": 92, "sent": 16, "replied": 8, "hot": 2, "meeting": 2
  }
}
```

**Важно:** добавление нового ключа в `by_platform` (например `"kariyer"`, `"habr"`) автоматически рендерит новую карточку в дашборде. Никаких правок UI не нужно.

## agents.json

Массив активных + недавно завершённых агентов:

```json
[
  {
    "id": "a1",                          // unique run_id
    "name": "outreach-avito",
    "status": "running",                 // running | idle | error
    "started_at": "11:15:00",
    "last_heartbeat": "15:00:01",        // обновляется каждые 30s пока агент жив
    "current_action": "send 5/9 → ...",  // 1-line описание текущего шага
    "sent": 5,
    "errors": 0
  }
]
```

## events-recent.json

Последние ~200 событий, отсортированные по `ts` ASC. Дашборд показывает их в live log feed. Полный лог идёт в `events.jsonl`.

```json
[
  {
    "ts": "12:52:14",                              // HH:MM:SS
    "level": "OK",                                 // INFO | OK | WARN | ERR | HOT
    "platform": "avito_rabota",
    "agent": "outreach-avito",
    "type": "send_done",                           // см. словарь ниже
    "message": "hlebnaya-usadba — Маркетолог DELIVERED",
    "meta": { "vacancy_id": "8018669014", "score": 25 }   // произвольные доп.поля
  }
]
```

## Уровни логов

| Level | Когда использовать | Цвет в дашборде |
|---|---|---|
| `INFO` | Информационные события: scan_start, throttle, heartbeat, filter применён | синий |
| `OK`   | Успешное действие: send_done, crm_upsert, reply_sent | зелёный |
| `WARN` | Что-то пошло не идеально, но обработано: blacklist_drop, soft_decline, review_hold | амбер |
| `ERR`  | Ошибка: send_failed, auth_failed, timeout | красный |
| `HOT`  | Горячий лид: reply_received с положительным intent, stage→MEETING | оранжевый акцент |

## Словарь `type` (используй существующие, добавляй новые согласованно)

### Lifecycle
- `agent_start` — агент запустился
- `agent_done` — агент завершился (нормально)
- `agent_error` — агент упал
- `heartbeat` — каждые 30s пока жив (показывает uptime, current_action)

### Auth / Session
- `auth_check` — проверил креды
- `session_open` / `session_close` — playwright session
- `auth_refresh` — токен обновлён (SJ 401/410)

### Scan
- `scan_start` — начал scan, `meta: {keyword, window, max}`
- `scan_progress` — пагинация / прогресс
- `scan_done` — finished, `meta: {raw, after_dedup}`

### Filter / Score
- `filter_dedup` — отброшено как уже отправленное
- `filter_salary` — отброшено по min salary
- `blacklist_drop` — `meta: {rule, match}`
- `filter_resume` — отброшено как резюме (не вакансия)
- `score_compute` — `meta: {scored, threshold}`
- `review_hold` — попало в HITL bucket (privacy/data-harvesting)

### Enrich
- `enrich_detail` — description loader fetched details, `meta: {ok, timeouts}`
- `detail_fetch_fail` — конкретный fetch упал

### Send
- `send_queue` — добавлено в очередь, `meta: {queued}`
- `send_attempt` — попытка отправки
- `send_done` — успех, `meta: {vacancy_id, channel}`
- `send_failed` — фейл, `meta: {http_code, error}`
- `send_throttle` — пауза между, `meta: {delay_s}`

### CRM (Twenty)
- `crm_upsert` — Opportunity создан/обновлён, `meta: {opp_id, stage}`
- `crm_touch` — hhTouch event записан, `meta: {touch_id}`
- `stage_transition` — stage изменён, `meta: {opp_id, from, to}`

### Replies
- `replies_poll_start` / `replies_poll_done`
- `reply_received` — пришёл ответ, `meta: {classified}` (level=HOT если intent=interest)
- `reply_classify` — классификация ответа
- `reply_sent` — отправлен авто-ответ
- `reply_skipped` — HITL bucket (unclear intent)

### Anti-bot / errors
- `anti_bot_block` — captcha/firewall/rate-limit, `meta: {reason}`
- `quota_block` — daily quota reached
- `error` — generic catch-all, `meta: {err}`

## Helper модуль (рекомендуемый)

### Node.js

`~/outreach-hunt/core/dashboard.mjs`:

```javascript
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const DASH_DIR = path.join(os.homedir(), 'zinin-corp-dashboard', 'outreach', 'data');
const EVENTS_LOG = path.join(DASH_DIR, 'events.jsonl');
const EVENTS_RECENT = path.join(DASH_DIR, 'events-recent.json');
const HEARTBEAT_INTERVAL_MS = 30_000;

let _heartbeats = new Map();   // agent.id → setInterval handle

function nowTs() {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map(n => String(n).padStart(2, '0')).join(':');
}

export async function logEvent({ level, platform, agent, type, message, meta = {} }) {
  await fs.mkdir(DASH_DIR, { recursive: true });
  const evt = { ts: nowTs(), level, platform, agent, type, message, meta };
  await fs.appendFile(EVENTS_LOG, JSON.stringify(evt) + '\n');
  // hot-tail recent
  let recent = [];
  try { recent = JSON.parse(await fs.readFile(EVENTS_RECENT, 'utf8')); } catch {}
  recent.push(evt);
  if (recent.length > 200) recent = recent.slice(-200);
  await fs.writeFile(EVENTS_RECENT, JSON.stringify(recent, null, 2));
}

export async function startHeartbeat(agent) {
  const tick = () => updateAgent({ ...agent, last_heartbeat: nowTs(), status: 'running' });
  await tick();
  const h = setInterval(tick, HEARTBEAT_INTERVAL_MS);
  _heartbeats.set(agent.id, h);
}
export function stopHeartbeat(agentId) {
  const h = _heartbeats.get(agentId);
  if (h) clearInterval(h);
  _heartbeats.delete(agentId);
}

async function updateAgent(agent) {
  const f = path.join(DASH_DIR, 'agents.json');
  let arr = [];
  try { arr = JSON.parse(await fs.readFile(f, 'utf8')); } catch {}
  const i = arr.findIndex(a => a.id === agent.id);
  if (i >= 0) arr[i] = { ...arr[i], ...agent };
  else arr.push(agent);
  await fs.writeFile(f, JSON.stringify(arr, null, 2));
}

export async function bumpStat(platform, key, delta = 1) {
  const f = path.join(DASH_DIR, 'stats.json');
  let s;
  try { s = JSON.parse(await fs.readFile(f, 'utf8')); }
  catch { s = { date: new Date().toISOString().slice(0,10), totals_today:{sent:0,replies:0,hot:0,errors:0}, by_platform:{}, twenty:{opportunities_total:0,by_stage:{}}, funnel:{scanned:0,filtered:0,sent:0,replied:0,hot:0,meeting:0} }; }
  s.by_platform[platform] = s.by_platform[platform] || {};
  s.by_platform[platform][key] = (s.by_platform[platform][key] || 0) + delta;
  if (key === 'sent' || key === 'replies' || key === 'hot' || key === 'errors') {
    s.totals_today[key] = (s.totals_today[key] || 0) + delta;
  }
  s.by_platform[platform].last_action_ts = nowTs();
  await fs.writeFile(f, JSON.stringify(s, null, 2));
}
```

### Python (для SuperJob / GulfTalent / любых Python агентов)

`~/zinin-corp-dashboard/outreach/data/dashboard.py`:

```python
"""Dashboard logging helper. Best-effort, never blocks agent."""
from __future__ import annotations
import json
import os
import time
from datetime import datetime
from pathlib import Path

DASH_DIR = Path.home() / "zinin-corp-dashboard" / "outreach" / "data"
EVENTS_LOG = DASH_DIR / "events.jsonl"
EVENTS_RECENT = DASH_DIR / "events-recent.json"

def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log_event(level: str, platform: str, agent: str, type: str, message: str, meta: dict | None = None) -> None:
    DASH_DIR.mkdir(parents=True, exist_ok=True)
    evt = {"ts": _now_ts(), "level": level, "platform": platform, "agent": agent, "type": type, "message": message, "meta": meta or {}}
    try:
        with EVENTS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
        # hot-tail recent
        recent = []
        if EVENTS_RECENT.is_file():
            try:
                recent = json.loads(EVENTS_RECENT.read_text(encoding="utf-8"))
            except Exception:
                pass
        recent.append(evt)
        if len(recent) > 200:
            recent = recent[-200:]
        EVENTS_RECENT.write_text(json.dumps(recent, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # never block agent on logging failure
```

## Multi-agent / parallel sessions

Когда параллельно работают несколько агентов (например Claude session #1 — Avito, session #2 — GulfTalent), они **все пишут в один и тот же файл** `events.jsonl` через `appendFile` (атомарный POSIX write для строк <PIPE_BUF). Никаких локов не нужно.

Дашборд читает merged view из `events-recent.json` который перестраивается каждый раз когда любой агент дописывает событие.

## Принцип логирования (Tim 2026-05-05): «логировать всё»

- Каждый scan → `scan_start` + `scan_done`
- Каждый отброс → `blacklist_drop` / `filter_*`
- Каждая отправка → `send_attempt` + `send_done`/`send_failed`
- Каждая throttle пауза → `send_throttle`
- Каждая запись в Twenty → `crm_upsert` / `crm_touch`
- Каждые 30 секунд жизни агента → `heartbeat`
- Каждый ответ → `reply_received` + `reply_classify` (+ `reply_sent` если auto-reply)

Принцип: **если действие занимает >2 секунды или меняет состояние — оно лога заслуживает.**
