import json
from datetime import datetime, timedelta, timezone

from news import history

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def test_load_returns_empty_dict_when_missing(tmp_path):
    assert history.load(str(tmp_path / 'nope.json')) == {}


def test_load_returns_empty_dict_on_corrupt_file(tmp_path):
    path = tmp_path / 'broken.json'
    path.write_text('{not json', encoding='utf-8')
    assert history.load(str(path)) == {}


def test_record_increments_count():
    raw = {}
    raw = history.record(raw, ['https://a.com/1'], NOW)
    raw = history.record(raw, ['https://a.com/1'], NOW)
    assert raw['https://a.com/1']['count'] == 2


def test_counts_extracts_ints():
    raw = {'https://a.com/1': {'count': 3, 'last': '2026-08-11T12:00:00Z'}}
    assert history.counts(raw) == {'https://a.com/1': 3}


def test_prune_drops_entries_older_than_retention():
    old = (NOW - timedelta(hours=49)).strftime('%Y-%m-%dT%H:%M:%SZ')
    recent = (NOW - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    raw = {
        'https://a.com/old': {'count': 5, 'last': old},
        'https://a.com/new': {'count': 1, 'last': recent},
    }
    kept = history.prune(raw, NOW)
    assert 'https://a.com/old' not in kept
    assert 'https://a.com/new' in kept


def test_prune_drops_malformed_entries():
    raw = {'https://a.com/bad': {'count': 1, 'last': 'garbage'}}
    assert history.prune(raw, NOW) == {}


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / 'seen.json')
    raw = history.record({}, ['https://a.com/1'], NOW)
    history.save(raw, path)
    assert history.load(path) == raw
    assert json.loads((tmp_path / 'seen.json').read_text(encoding='utf-8'))
