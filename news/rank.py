"""뉴스 기사 정규화·클러스터링·채점. 네트워크를 호출하지 않는다."""
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
