"""노출 이력 파일 관리. 기사 링크(정규화 키) 기준으로 노출 횟수를 센다."""
import json
from datetime import datetime, timedelta, timezone

HISTORY_PATH = 'seen_history.json'
RETENTION_HOURS = 48
_STAMP = '%Y-%m-%dT%H:%M:%SZ'


def load(path=HISTORY_PATH):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def counts(raw):
    return {k: v.get('count', 0) for k, v in raw.items() if isinstance(v, dict)}


def record(raw, keys, now):
    stamp = now.strftime(_STAMP)
    for key in keys:
        entry = raw.setdefault(key, {'count': 0, 'last': stamp})
        entry['count'] = entry.get('count', 0) + 1
        entry['last'] = stamp
    return raw


def prune(raw, now, retention_hours=RETENTION_HOURS):
    cutoff = now - timedelta(hours=retention_hours)
    kept = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            last = datetime.strptime(value['last'], _STAMP).replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if last >= cutoff:
            kept[key] = value
    return kept


def save(raw, path=HISTORY_PATH):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=2, sort_keys=True)
