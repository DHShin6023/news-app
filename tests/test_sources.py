from datetime import timezone
from pathlib import Path

from news.sources import parse_pubdate, parse_google_rss

FIXTURES = Path(__file__).parent / 'fixtures'


def test_parse_pubdate_handles_gmt():
    dt = parse_pubdate('Tue, 11 Aug 2026 06:14:03 GMT')
    assert dt.year == 2026 and dt.hour == 6
    assert dt.tzinfo is not None


def test_parse_pubdate_converts_kst_to_utc():
    dt = parse_pubdate('Tue, 11 Aug 2026 15:00:00 +0900')
    assert dt.astimezone(timezone.utc).hour == 6


def test_parse_pubdate_returns_none_on_garbage():
    assert parse_pubdate('') is None
    assert parse_pubdate('not a date') is None


def test_parse_google_rss_extracts_fields():
    arts = parse_google_rss((FIXTURES / 'google_search.xml').read_bytes())
    first = arts[0]
    assert first.title == '서울 집값 1년 만에 15% 급등 - 매일일보'
    assert first.outlet == '매일일보'
    assert first.origin == 'google'
    assert first.rank == 0
    # 원본 링크는 그대로 두고, key만 추적 파라미터를 제거한다
    assert 'utm_source' in first.link
    assert 'utm_source' not in first.key


def test_parse_google_rss_builds_link_from_guid():
    # link가 없고 guid만 있는 항목은 예전에 404를 유발했다
    arts = parse_google_rss((FIXTURES / 'google_search.xml').read_bytes())
    second = arts[1]
    assert second.link.startswith('https://news.google.com/articles/')


def test_parse_google_rss_skips_undated_items():
    arts = parse_google_rss((FIXTURES / 'google_search.xml').read_bytes())
    assert all('날짜없음' not in a.title for a in arts)


def test_parse_google_rss_respects_limit():
    arts = parse_google_rss((FIXTURES / 'google_search.xml').read_bytes(), limit=1)
    assert len(arts) == 1


import json
import pytest
from news.sources import parse_naver, fetch_naver_search, NaverCredentialsMissing


def load_naver_fixture():
    return json.loads((FIXTURES / 'naver_news.json').read_text(encoding='utf-8'))


def test_parse_naver_strips_html_from_title():
    arts = parse_naver(load_naver_fixture())
    assert arts[0].title == '서울 집값 1년 만에 15% 급등 "규제 무색"'


def test_parse_naver_uses_originallink():
    arts = parse_naver(load_naver_fixture())
    assert arts[0].link == 'https://www.mdilbo.com/detail/xyz'


def test_parse_naver_derives_outlet_from_domain():
    arts = parse_naver(load_naver_fixture())
    assert arts[0].outlet == 'mdilbo.com'
    assert arts[1].outlet == 'hankyung.com'


def test_parse_naver_sets_origin_and_rank():
    arts = parse_naver(load_naver_fixture())
    assert [a.origin for a in arts] == ['naver'] * 3
    assert [a.rank for a in arts] == [0, 1, 2]


def test_fetch_naver_search_raises_without_credentials(monkeypatch):
    monkeypatch.delenv('NAVER_CLIENT_ID', raising=False)
    monkeypatch.delenv('NAVER_CLIENT_SECRET', raising=False)
    with pytest.raises(NaverCredentialsMissing):
        fetch_naver_search('코스피')


from news.sources import count_naver_matches


def test_count_naver_matches_counts_similar_titles(monkeypatch):
    fixture = parse_naver(load_naver_fixture())
    monkeypatch.setattr('news.sources.fetch_naver_search',
                        lambda *args, **kwargs: fixture)
    # 집값 기사 2건은 유사, 스포츠 1건은 무관
    assert count_naver_matches('서울 집값 1년 만에 15% 급등') == 2


def test_count_naver_matches_returns_zero_on_empty_query(monkeypatch):
    monkeypatch.setattr('news.sources.fetch_naver_search',
                        lambda *args, **kwargs: [])
    assert count_naver_matches('!!') == 0
