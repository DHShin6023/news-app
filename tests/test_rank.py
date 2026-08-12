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
