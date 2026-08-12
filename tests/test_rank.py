from news.rank import link_key


def test_link_key_strips_tracking_params():
    url = 'http://www.newsworks.co.kr/news/articleView.html?idxno=123&utm_source=naver'
    assert link_key(url) == 'https://newsworks.co.kr/news/articleView.html?idxno=123'


def test_link_key_preserves_article_id():
    # 국내 CMS는 기사 ID를 쿼리에 담는다. 통째로 지우면 모든 기사가 한 키로 뭉개진다
    a = link_key('https://newsworks.co.kr/news/articleView.html?idxno=123')
    b = link_key('https://newsworks.co.kr/news/articleView.html?idxno=456')
    assert a != b


def test_link_key_normalizes_host_and_scheme():
    a = link_key('http://WWW.Example.com/news/1/')
    b = link_key('https://example.com/news/1')
    assert a == b


def test_link_key_sorts_remaining_params():
    a = link_key('https://example.com/a?b=2&a=1')
    b = link_key('https://example.com/a?a=1&b=2')
    assert a == b


from news.rank import clean_title, content_words, title_tokens, is_similar, verification_query


def test_clean_title_strips_html_and_entities():
    # 네이버 API는 검색어를 <b>로 감싸고 HTML 엔티티를 그대로 준다
    assert clean_title('<b>코스피</b> 상승 &quot;외국인 순매수&quot;') == '코스피 상승 "외국인 순매수"'


def test_content_words_drops_outlet_suffix():
    words = content_words('코스피 상승 마감 - 한강타임즈')
    assert '한강타임즈' not in words
    assert words == ['코스피', '상승', '마감']


def test_content_words_keeps_order():
    assert content_words('서울 집값 급등') == ['서울', '집값', '급등']


def test_title_tokens_drops_single_chars():
    assert title_tokens('삼성전자 주 상승') == {'삼성전자', '상승'}


def test_is_similar_matches_same_event():
    a = title_tokens('서울 집값 1년 만에 15% 급등')
    b = title_tokens('서울 집값 1년 만에 15% 올라')
    assert is_similar(a, b)


def test_is_similar_rejects_different_events():
    a = title_tokens('서울 집값 1년 만에 15% 급등')
    b = title_tokens('비트코인 역프리미엄 장기화 이유는')
    assert not is_similar(a, b)


def test_is_similar_handles_empty():
    assert not is_similar(set(), title_tokens('서울 집값 급등'))


def test_verification_query_takes_leading_words():
    q = verification_query('이 대통령, 세법개정안 구윤철에 지시 - 경향신문')
    assert q == '대통령 세법개정안 구윤철에 지시'


from datetime import datetime, timezone
from news.rank import Article, Cluster, cluster_articles


def make_article(title, origin='google', rank=0, outlet='매체A', hours_ago=0, link=None):
    link = link or f'https://example.com/{abs(hash(title)) % 100000}'
    published = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    published = published.replace(hour=12 - hours_ago)
    return Article(
        title=title, link=link, key=link_key(link), published=published,
        outlet=outlet, origin=origin, rank=rank,
    )


def test_cluster_groups_same_event():
    arts = [
        make_article('서울 집값 1년 만에 15% 급등', origin='google', rank=0),
        make_article('서울 집값 1년 만에 15% 올라', origin='naver', rank=1),
        make_article('비트코인 역프리미엄 장기화 이유는', origin='google', rank=2),
    ]
    clusters = cluster_articles(arts)
    assert len(clusters) == 2
    assert len(clusters[0].articles) == 2


def test_cluster_drops_non_articles():
    # 토큰 3개 미만은 종목 시세 페이지 등 비기사로 본다
    arts = [make_article('삼성전자 주가'), make_article('서울 집값 15% 급등 소식')]
    clusters = cluster_articles(arts)
    assert len(clusters) == 1


def test_cluster_origins_and_best_rank():
    arts = [
        make_article('서울 집값 1년 만에 15% 급등', origin='google', rank=5),
        make_article('서울 집값 1년 만에 15% 올라', origin='naver', rank=2),
    ]
    c = cluster_articles(arts)[0]
    assert c.origins == {'google', 'naver'}
    assert c.best_rank == 2


def test_outlet_count_uses_max_per_origin():
    # 구글은 '뉴스웍스', 네이버는 'newsworks.co.kr' — 같은 매체지만 문자열이 다르다.
    # origin별로 세고 최댓값을 취해 중복 계산을 막는다
    arts = [
        make_article('서울 집값 1년 만에 15% 급등', origin='google', outlet='뉴스웍스', rank=0),
        make_article('서울 집값 1년 만에 15% 올라', origin='google', outlet='한강타임즈', rank=1),
        make_article('서울 집값 1년 만에 15% 상승', origin='naver', outlet='newsworks.co.kr', rank=0),
    ]
    c = cluster_articles(arts)[0]
    assert c.outlet_count == 2


def test_cluster_newest_is_latest_published():
    arts = [
        make_article('서울 집값 1년 만에 15% 급등', hours_ago=5),
        make_article('서울 집값 1년 만에 15% 올라', hours_ago=1),
    ]
    c = cluster_articles(arts)[0]
    assert c.newest.hour == 11


import pytest
from news.rank import (
    freshness_score, cross_score, rank_score, outlet_score,
    importance_score, history_penalty,
)

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def at(hours_ago):
    from datetime import timedelta
    return NOW - timedelta(hours=hours_ago)


def test_freshness_halves_every_six_hours():
    assert freshness_score(at(0), NOW) == pytest.approx(100.0)
    assert freshness_score(at(6), NOW) == pytest.approx(50.0)
    assert freshness_score(at(12), NOW) == pytest.approx(25.0)
    assert freshness_score(at(24), NOW) == pytest.approx(6.25)


def test_freshness_clamps_future_dates():
    # 발행 시각이 미래로 오는 피드가 있다. 100을 넘기지 않는다
    assert freshness_score(at(-3), NOW) == pytest.approx(100.0)


def test_cross_score_requires_both_origins():
    both = Cluster(articles=[
        make_article('서울 집값 15% 급등', origin='google'),
        make_article('서울 집값 15% 올라', origin='naver'),
    ])
    google_only = Cluster(articles=[make_article('서울 집값 15% 급등', origin='google')])
    assert cross_score(both) == 40.0
    assert cross_score(google_only) == 0.0


def test_cross_score_uses_naver_matches_when_set():
    c = Cluster(articles=[make_article('천안 교회 어린이 사망', origin='google')])
    c.naver_matches = 1
    assert cross_score(c) == 0.0
    c.naver_matches = 3
    assert cross_score(c) == 40.0


def test_rank_score_scales_and_clamps():
    assert rank_score(Cluster(articles=[make_article('가 나 다', rank=0)])) == pytest.approx(35.0)
    assert rank_score(Cluster(articles=[make_article('가 나 다', rank=10)])) == pytest.approx(17.5)
    # 20위를 넘어도 음수가 되지 않는다
    assert rank_score(Cluster(articles=[make_article('가 나 다', rank=25)])) == 0.0


def test_outlet_score_steps():
    def cluster_with(n):
        return Cluster(articles=[
            make_article(f'서울 집값 15% 급등 보도{i}', origin='google', outlet=f'매체{i}')
            for i in range(n)
        ])
    assert outlet_score(cluster_with(1)) == 0.0
    assert outlet_score(cluster_with(3)) == pytest.approx(12.5)
    assert outlet_score(cluster_with(5)) == pytest.approx(25.0)
    assert outlet_score(cluster_with(8)) == pytest.approx(25.0)


def test_importance_is_sum_of_three():
    c = Cluster(articles=[
        make_article('서울 집값 15% 급등', origin='google', outlet='A', rank=0),
        make_article('서울 집값 15% 올라', origin='naver', outlet='b.co.kr', rank=0),
    ])
    assert importance_score(c) == pytest.approx(40.0 + 35.0 + 0.0)


def test_history_penalty_caps_at_60():
    assert history_penalty(0) == 0.0
    assert history_penalty(1) == 12.0
    assert history_penalty(5) == 60.0
    assert history_penalty(7) == 60.0


from news.rank import pick_representative, total_score, select_top


def test_representative_prefers_unseen_article():
    seen = make_article('서울 집값 15% 급등', origin='google', link='https://a.com/1')
    fresh = make_article('서울 집값 15% 올라', origin='google', link='https://a.com/2')
    c = Cluster(articles=[seen, fresh])
    history = {seen.key: 4, fresh.key: 0}
    assert pick_representative(c, history).link == 'https://a.com/2'


def test_representative_prefers_newer_when_history_equal():
    old = make_article('서울 집값 15% 급등', link='https://a.com/1', hours_ago=6)
    new = make_article('서울 집값 15% 올라', link='https://a.com/2', hours_ago=1)
    c = Cluster(articles=[old, new])
    assert pick_representative(c, {}).link == 'https://a.com/2'


def test_representative_prefers_naver_original_link_on_tie():
    g = make_article('서울 집값 15% 급등', origin='google', link='https://news.google.com/x')
    n = make_article('서울 집값 15% 급등', origin='naver', link='https://a.com/1')
    c = Cluster(articles=[g, n])
    assert pick_representative(c, {}).origin == 'naver'


def test_total_score_subtracts_history_of_representative():
    art = make_article('서울 집값 15% 급등', origin='google', rank=0, hours_ago=0)
    c = Cluster(articles=[art])
    clean = total_score(c, NOW, {})
    penalized = total_score(c, NOW, {art.key: 5})
    assert clean - penalized == pytest.approx(60.0)


def test_select_top_returns_highest_scoring_representatives():
    strong = Cluster(articles=[
        make_article('서울 집값 1년 만에 15% 급등', origin='google', outlet='A', rank=0),
        make_article('서울 집값 1년 만에 15% 올라', origin='naver', outlet='b.co.kr', rank=0),
    ])
    weak = Cluster(articles=[
        make_article('국힘 주거지옥 몰고 등쳐먹어 논평', origin='google', outlet='C', rank=3, hours_ago=6),
    ])
    top = select_top([weak, strong], NOW, {}, max_items=1)
    assert len(top) == 1
    assert '집값' in top[0].title


def test_select_top_respects_max_items():
    clusters = [
        Cluster(articles=[make_article(f'사건 {i} 대형 보도 발생', rank=i)])
        for i in range(6)
    ]
    assert len(select_top(clusters, NOW, {}, max_items=3)) == 3


def test_regression_stale_op_ed_loses_to_fresh_indicator():
    """2026-08-11 관측 사례. 11회 노출된 정당 논평이 신선한 지표 기사에 진다."""
    op_ed = make_article(
        '국힘 與 청년들 주거지옥 몰고 주식계좌 녹여 등쳐먹어',
        origin='google', outlet='C', rank=3, hours_ago=6, link='https://c.com/op',
    )
    indicator = [
        make_article('서울 집값 1년 만에 15% 급등 규제 이후에도 상승',
                     origin='google', outlet='매일일보', rank=0, hours_ago=2,
                     link='https://m.com/1'),
        make_article('서울 집값 1년 만에 15% 뛰어 규제 이후에도 올라',
                     origin='naver', outlet='mdilbo.co.kr', rank=0, hours_ago=2,
                     link='https://m.com/2'),
    ]
    clusters = cluster_articles([op_ed] + indicator)
    history = {op_ed.key: 11}
    top = select_top(clusters, NOW, history, max_items=1)
    assert '집값' in top[0].title


from news.rank import drop_stale


def aged_article(title, hours_ago):
    """make_article은 hour를 치환해 24시간을 못 넘는다. 여기서는 timedelta로 만든다."""
    from datetime import timedelta
    link = f'https://example.com/{abs(hash(title)) % 100000}'
    return Article(
        title=title, link=link, key=link_key(link),
        published=NOW - timedelta(hours=hours_ago),
        outlet='매체A', origin='google', rank=0,
    )


def test_drop_stale_removes_articles_older_than_24h():
    # 네이버 검색 API에는 기간 필터가 없어 8일 전 기사도 섞여 들어온다
    fresh = aged_article('서울 집값 15% 급등 소식', 3)
    stale = aged_article('지난주 부동산 대책 논란 정리', 30)
    assert drop_stale([fresh, stale], NOW) == [fresh]


def test_drop_stale_keeps_articles_just_under_24h():
    # 23.9시간 전이라도 중요하면 노출하는 것이 맞다 (신동환 판단, 2026-08-12)
    art = aged_article('연준 금리 동결 결정 배경', 23.9)
    assert drop_stale([art], NOW) == [art]


def test_drop_stale_keeps_exactly_24h():
    art = aged_article('연준 금리 동결 결정 배경', 24)
    assert drop_stale([art], NOW) == [art]


def test_drop_stale_keeps_future_dated_articles():
    # 발행 시각이 미래로 오는 피드가 있다. 신선도는 100으로 클램프되므로 버리지 않는다
    art = aged_article('속보 기사', -2)
    assert drop_stale([art], NOW) == [art]
