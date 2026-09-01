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


def aged(title, hours_ago, link):
    from datetime import timedelta
    return Article(title=title, link=link, key=link_key(link),
                   published=NOW - timedelta(hours=hours_ago),
                   outlet='A', origin='google', rank=0)


def test_build_category_drops_articles_older_than_24h(monkeypatch):
    # 네이버·Top Stories에는 기간 필터가 없어 며칠 전 기사가 섞여 들어온다
    monkeypatch.setattr(fetch_news.sources, 'fetch_google_search',
                        lambda q, limit=20: [
                            aged('지난주 부동산 대책 논란 정리', 30, 'https://a.com/old'),
                            aged('오늘 서울 집값 급등 소식', 2, 'https://a.com/new'),
                        ])
    monkeypatch.setattr(fetch_news.sources, 'fetch_naver_search',
                        lambda *a, **k: [])

    cat = {'id': 'cat-land', 'queries': ['부동산'], 'max_items': 5}
    articles, _ = fetch_news.build_category(cat, NOW, {})
    assert [a.link for a in articles] == ['https://a.com/new']


def test_build_category_gate_drops_domestic_article_from_us(monkeypatch):
    # 2026-09-01 실사례: 네이버 최신순이 '나스닥' 쿼리에 국내 증시 기사를 물어왔다
    monkeypatch.setattr(fetch_news.sources, 'fetch_google_search',
                        lambda q, limit=20: [])
    monkeypatch.setattr(fetch_news.sources, 'fetch_naver_search',
                        lambda q, sort='sim', limit=20: [
                            make('뉴욕증시, 미·이란 교전 재개에 하락 마감',
                                 origin='naver', link='https://a.com/us'),
                            make('장 초반 약세 삼전닉스 하락 폭 만회 닉스 오르고 삼전 보합',
                                 origin='naver', link='https://a.com/kr'),
                        ])

    cat = next(c for c in fetch_news.CATEGORIES if c['id'] == 'cat-us')
    articles, _ = fetch_news.build_category(cat, NOW, {})
    assert [a.link for a in articles] == ['https://a.com/us']


def test_build_category_gate_keeps_kr_article_citing_us_market(monkeypatch):
    monkeypatch.setattr(fetch_news.sources, 'fetch_google_search',
                        lambda q, limit=20: [])
    monkeypatch.setattr(fetch_news.sources, 'fetch_naver_search',
                        lambda q, sort='sim', limit=20: [
                            make('코스피 뉴욕증시 하락에 6780선 약세 마감',
                                 origin='naver', link='https://a.com/kr'),
                        ])

    cat = next(c for c in fetch_news.CATEGORIES if c['id'] == 'cat-kr')
    articles, _ = fetch_news.build_category(cat, NOW, {})
    assert [a.link for a in articles] == ['https://a.com/kr']


def test_build_category_gate_does_not_empty_category(monkeypatch):
    # 게이트가 전부 걷어내도 카테고리를 비우지 않는다 (이전 데이터가 굳는 것을 막는다)
    monkeypatch.setattr(fetch_news.sources, 'fetch_google_search',
                        lambda q, limit=20: [])
    monkeypatch.setattr(fetch_news.sources, 'fetch_naver_search',
                        lambda q, sort='sim', limit=20: [
                            make('코스피 삼전 반등 마감 소식', origin='naver',
                                 link='https://a.com/kr'),
                        ])

    cat = next(c for c in fetch_news.CATEGORIES if c['id'] == 'cat-us')
    articles, _ = fetch_news.build_category(cat, NOW, {})
    assert articles is not None and len(articles) == 1
