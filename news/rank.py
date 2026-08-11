"""뉴스 기사 정규화·클러스터링·채점. 네트워크를 호출하지 않는다."""
import html
import re
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
