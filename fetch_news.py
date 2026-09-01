"""카테고리별 뉴스를 수집해 news_data.json으로 저장한다."""
import json
from datetime import datetime, timezone

from news import history, rank, sources

DATA_PATH = 'news_data.json'

# 카테고리 주제 게이트. 토큰은 제목에 대한 부분 문자열이며 전부 소문자로 적는다.
# own은 카테고리를 확정하는 토큰(exclude보다 우선), exclude는 '이 카테고리일 리 없는' 토큰.
KR_MARKET = (
    '코스피', '코스닥', '국내증시', '국장', '삼성전자', '삼전', '하이닉스',
    '유가증권시장', '원달러', '원·달러', '코넥스', '9천피', '여의도 증권가',
)
US_MARKET = (
    '뉴욕증시', '나스닥', '다우지수', 's&p', '미증시', '미 증시', '美 증시',
    '월가', '월스트리트',
)

CATEGORIES = [
    {'id': 'cat-us', 'max_items': 3, 'queries': [
        '나스닥 뉴욕증시 S&P500',
        '연준 금리 미국 경제지표',
        '엔비디아 테슬라 애플 빅테크',
    ], 'gate': {
        # own 없음 — 미국 기사가 '코스피'를 제목에 다는 일은 없어 exclude가 항상 옳다
        'exclude': KR_MARKET,
        'require_any': US_MARKET + (
            '美', '미국', '연준', 'fed', 'fomc', 'ism', '파월', '워시', '베선트',
            '잭슨홀', '미국채', '미 국채', '미 장기국채', '트럼프', '엔비디아',
            '테슬라', '애플', '아마존', '마이크로소프트', '브로드컴', '빅테크',
            '뉴욕', '워싱턴',
        ),
    }},
    {'id': 'cat-kr', 'max_items': 3, 'queries': [
        '코스피 코스닥 주식시장',
        '삼성전자 반도체 실적 국내증시',
    ], 'gate': {
        # 국내 기사가 미국장을 인용하는 건 흔하다. KR 토큰이 있으면 그것으로 확정한다
        'own': KR_MARKET,
        'exclude': US_MARKET,
        'require_any': (
            '증시', '주식시장', '증권가', '예탁금', '빚투', '신용거래', '거래대금',
            '순매수', '순매도', '자사주', '공모주', '기업공개', '상장', '반도체',
            '2차전지', '주도주', '금융위', '금감원', '개미', 'etf',
        ),
    }},
    {'id': 'cat-coin', 'max_items': 3, 'queries': [
        '비트코인 이더리움 시세',
        '암호화폐 규제 거래소 알트코인',
    ], 'gate': {'require_any': (
        '비트코인', '이더리움', '코인', '암호화폐', '가상자산', '블록체인',
        '리플', '솔라나', '도지', '에이다', '스테이블', '디지털자산',
        'btc', 'eth', 'xrp', '업비트', '빗썸', '바이낸스', '크라켄', '테더',
        '알트', '토큰', '디파이', '온체인', '스테이킹', '채굴', 'nft',
    )}},
    {'id': 'cat-land', 'max_items': 3, 'queries': [
        '부동산 아파트 매매가격',
        '전세 청약 분양 부동산정책',
    ], 'gate': {'require_any': (
        '부동산', '아파트', '집값', '전세', '전셋값', '월세', '청약', '분양',
        '재건축', '재개발', '정비사업', '매매가', '매물', '급매', '경매', '국평',
        '주택', '주거', '실거주', '임대', '임대차', '보증금', '오피스텔',
        '공시가격', '다주택', '주담대', 'ltv', 'dsr', '국토부', '신도시',
        '상가', '토지', '입주',
    )}},
    # cat-etc는 Top Stories 전반이라 주제를 좁히지 않는다
    {'id': 'cat-etc', 'max_items': 5, 'queries': None},
]


def _collect_search(cat):
    """쿼리 기반 카테고리. (기사 목록, 실패한 소스 목록)을 반환한다."""
    articles, degraded = [], []
    google_ok = naver_ok = False
    for query in cat['queries']:
        try:
            articles += sources.fetch_google_search(query)
            google_ok = True
        except Exception as exc:
            print(f"  {cat['id']} 구글 '{query}' 실패: {exc}")
        for sort in ('sim', 'date'):
            try:
                articles += sources.fetch_naver_search(query, sort=sort)
                naver_ok = True
            except Exception as exc:
                print(f"  {cat['id']} 네이버({sort}) '{query}' 실패: {exc}")
    if not google_ok:
        degraded.append('google')
    if not naver_ok:
        degraded.append('naver')
    return articles, degraded


def _collect_top_stories(cat):
    try:
        return sources.fetch_google_top_stories(), []
    except Exception as exc:
        print(f"  {cat['id']} Top Stories 실패: {exc}")
        return [], ['google']


def _annotate_naver_matches(clusters, cat_id):
    """cat-etc 전용. 대표 제목으로 네이버를 재검색해 교차 근거를 채운다."""
    failures = 0
    for cluster in clusters:
        title = cluster.articles[0].title
        try:
            cluster.naver_matches = sources.count_naver_matches(title)
        except Exception as exc:
            print(f'  {cat_id} 네이버 검증 실패: {exc}')
            failures += 1
    if failures == len(clusters) and clusters:
        # 전부 실패하면 교차 점수를 끄고 순위·매체폭으로만 경쟁시킨다
        for cluster in clusters:
            cluster.naver_matches = None
        return ['naver']
    return []


def build_category(cat, now, history_counts):
    if cat.get('queries'):
        articles, degraded = _collect_search(cat)
    else:
        articles, degraded = _collect_top_stories(cat)

    if not articles:
        return None, degraded

    articles = rank.drop_stale(articles, now)
    articles = rank.apply_category_gate(articles, cat.get('gate'))
    clusters = rank.cluster_articles(articles)
    if not cat.get('queries'):
        degraded += _annotate_naver_matches(clusters, cat['id'])
    if not clusters:
        return None, degraded

    return rank.select_top(clusters, now, history_counts, cat['max_items']), degraded


def to_json_items(articles):
    return [{
        'title': a.title,
        'link': a.link,
        'pubDate': a.published.strftime('%a, %d %b %Y %H:%M:%S %z'),
        'source': a.outlet,
    } for a in articles]


def _load_previous():
    try:
        with open(DATA_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    now = datetime.now(timezone.utc)
    previous = _load_previous()
    raw_history = history.prune(history.load(), now)
    counts = history.counts(raw_history)

    result, degraded_map, exposed_keys = {}, {}, []
    for cat in CATEGORIES:
        articles, degraded = build_category(cat, now, counts)
        if articles is None:
            # 모든 소스 실패 — 이전 데이터를 유지한다
            result[cat['id']] = previous.get(cat['id'], [])
            print(f"  {cat['id']}: 수집 실패, 이전 데이터 유지")
        else:
            result[cat['id']] = to_json_items(articles)
            exposed_keys += [a.key for a in articles]
            print(f"  {cat['id']}: {len(articles)}개 선택")
        if degraded:
            degraded_map[cat['id']] = degraded

    result['updated'] = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    if degraded_map:
        result['degraded'] = degraded_map

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    history.save(history.record(raw_history, exposed_keys, now))
    print(f"news_data.json 저장 완료 ({result['updated']})")


if __name__ == '__main__':
    main()
