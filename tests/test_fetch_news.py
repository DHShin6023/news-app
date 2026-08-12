from datetime import datetime, timezone

import fetch_news
from news.rank import Article, link_key

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def make(title, origin='google', rank=0, outlet='A', link='https://a.com/1'):
    return Article(title=title, link=link, key=link_key(link), published=NOW,
                   outlet=outlet, origin=origin, rank=rank)


def test_to_json_items_shape():
    items = fetch_news.to_json_items([make('서울 집값 15% 급등')])
    assert items == [{
        'title': '서울 집값 15% 급등',
        'link': 'https://a.com/1',
        'pubDate': 'Tue, 11 Aug 2026 12:00:00 +0000',
        'source': 'A',
    }]


def test_build_category_marks_naver_degraded(monkeypatch):
    monkeypatch.setattr(fetch_news.sources, 'fetch_google_search',
                        lambda q, limit=20: [make('서울 집값 15% 급등 보도')])

    def boom(*args, **kwargs):
        raise RuntimeError('naver down')
    monkeypatch.setattr(fetch_news.sources, 'fetch_naver_search', boom)

    cat = {'id': 'cat-land', 'queries': ['부동산'], 'max_items': 3}
    articles, degraded = fetch_news.build_category(cat, NOW, {})
    assert degraded == ['naver']
    assert len(articles) == 1


def test_build_category_returns_none_when_all_sources_fail(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('down')
    monkeypatch.setattr(fetch_news.sources, 'fetch_google_search', boom)
    monkeypatch.setattr(fetch_news.sources, 'fetch_naver_search', boom)

    cat = {'id': 'cat-land', 'queries': ['부동산'], 'max_items': 3}
    articles, degraded = fetch_news.build_category(cat, NOW, {})
    assert articles is None
    assert sorted(degraded) == ['google', 'naver']


def test_build_category_annotates_naver_matches_for_top_stories(monkeypatch):
    monkeypatch.setattr(fetch_news.sources, 'fetch_google_top_stories',
                        lambda limit=20: [
                            make('사설 천안 교회 어린이 사망 사건', link='https://a.com/op'),
                            make('이 대통령 세법개정안 구윤철에 지시', link='https://a.com/pol'),
                        ])
    monkeypatch.setattr(fetch_news.sources, 'count_naver_matches',
                        lambda title, limit=20: 0 if '사설' in title else 9)

    cat = {'id': 'cat-etc', 'queries': None, 'max_items': 1}
    articles, degraded = fetch_news.build_category(cat, NOW, {})
    assert degraded == []
    assert '세법개정안' in articles[0].title
