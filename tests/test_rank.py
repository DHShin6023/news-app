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
