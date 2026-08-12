"""뉴스 기사 정규화·클러스터링·채점. 네트워크를 호출하지 않는다."""
import html
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_PARAMS = {'ref', 'oc', 'fbclid', 'gclid', 'from', 'igshid', 'spm'}
TRACKING_PREFIXES = ('utm_',)


def _is_tracking(name):
    low = name.lower()
    return low in TRACKING_PARAMS or low.startswith(TRACKING_PREFIXES)


def link_key(url):
    """이력 조회용 정규화 키. 추적 파라미터만 제거하고 기사 ID는 보존한다."""
    parts = urlsplit(url)
    kept = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking(k)
    )
    host = parts.netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    path = parts.path.rstrip('/') or '/'
    return urlunsplit(('https', host, path, urlencode(kept), ''))


def clean_title(raw):
    """네이버가 주는 <b> 태그와 HTML 엔티티를 제거한다."""
    text = re.sub(r'<[^>]+>', '', raw or '')
    return html.unescape(text).strip()


def content_words(title):
    """비교용 어절 목록. 말미의 '- 언론사'와 특수문자를 제거한다."""
    text = re.sub(r'\s*-\s*[^-]+$', '', clean_title(title))
    text = re.sub(r'[^0-9A-Za-z가-힣 ]', ' ', text)
    return [w for w in text.split() if len(w) >= 2]


def title_tokens(title):
    return set(content_words(title))


def is_similar(a, b):
    """제목 토큰 겹침이 크면 같은 사건으로 본다."""
    if not a or not b:
        return False
    inter = len(a & b)
    if inter == 0:
        return False
    jaccard = inter / len(a | b)
    overlap = inter / min(len(a), len(b))
    return jaccard >= 0.4 or overlap >= 0.6


def verification_query(title, max_tokens=4):
    """cat-etc 검증용 네이버 검색어. 제목 앞부분 어절을 쓴다."""
    return ' '.join(content_words(title)[:max_tokens])


@dataclass(frozen=True)
class Article:
    title: str
    link: str      # 원본 URL — 사용자에게 노출되는 값
    key: str       # 정규화 URL — 이력 조회용
    published: object   # datetime (UTC)
    outlet: str
    origin: str    # 'google' | 'naver'
    rank: int      # 소스 내 순위 (0-based)


@dataclass
class Cluster:
    articles: list = field(default_factory=list)
    naver_matches: object = None   # int | None. cat-etc 검증 모드에서만 설정

    @property
    def origins(self):
        return {a.origin for a in self.articles}

    @property
    def outlet_count(self):
        # 구글과 네이버의 언론사 표기 형식이 달라 합치면 중복 계산된다.
        # origin별로 세고 최댓값을 취한다
        return max(
            len({a.outlet for a in self.articles if a.origin == 'google'}),
            len({a.outlet for a in self.articles if a.origin == 'naver'}),
        )

    @property
    def best_rank(self):
        return min(a.rank for a in self.articles)

    @property
    def newest(self):
        return max(a.published for a in self.articles)


def cluster_articles(articles):
    """제목 유사도로 같은 사건끼리 묶는다. 토큰 3개 미만은 비기사로 제외한다."""
    clusters = []
    token_lists = []   # 클러스터별 소속 기사들의 토큰 집합 목록
    for art in articles:
        tokens = title_tokens(art.title)
        if len(tokens) < 3:
            continue
        placed = False
        for idx, tokens_in_cluster in enumerate(token_lists):
            if any(is_similar(tokens, seen) for seen in tokens_in_cluster):
                clusters[idx].articles.append(art)
                tokens_in_cluster.append(tokens)
                placed = True
                break
        if not placed:
            clusters.append(Cluster(articles=[art]))
            token_lists.append([tokens])
    return clusters
