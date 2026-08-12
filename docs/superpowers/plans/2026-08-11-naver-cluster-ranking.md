# 뉴스앱 네이버 결합 + 클러스터 랭킹 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 구글 단독·관련도순 고정이던 뉴스 선택 로직을 구글+네이버 교차 검증 기반의 사건 클러스터 랭킹으로 교체해, 카테고리 회전율을 28~35%에서 60% 이상으로 올린다.

**Architecture:** 네트워크에 닿는 코드(`news/sources.py`)와 순수 계산 코드(`news/rank.py`)를 분리한다. 두 소스에서 모은 기사를 제목 토큰 유사도로 사건 단위 클러스터로 묶고, 클러스터마다 `0.5 × 신선도 + 0.5 × 중요도 − 노출이력감점`을 계산해 상위 N개의 대표 기사를 선출한다. LLM은 쓰지 않는다.

**Tech Stack:** Python 3.12, `requests`, 표준 라이브러리(`xml.etree`, `email.utils`, `urllib.parse`), pytest, GitHub Actions

**스펙:** `docs/superpowers/specs/2026-08-11-naver-cluster-ranking-design.md`

## Global Constraints

- 순위 판정에 LLM을 쓰지 않는다. 모든 점수는 숫자로 설명 가능해야 한다
- `rank.py`는 네트워크를 호출하지 않는다. 전부 순수 함수여야 한다
- 신선도 : 중요도 = 0.5 : 0.5. 중요도 = 교차(40) + 순위(35) + 매체폭(25)
- 반감기 6시간, 이력 감점 12점/회, 감점 상한 60점, cat-etc 교차 임계값 3건
- `Article.link`는 원본 URL(사용자 노출용), `Article.key`는 정규화 URL(이력 조회용). 둘을 섞지 않는다
- 쿼리스트링을 통째로 제거하지 않는다. 추적 파라미터만 선별 제거한다
- 카테고리는 서로 독립이다. 하나가 실패해도 나머지는 진행한다
- 카테고리의 모든 소스가 실패하면 이전 `news_data.json`의 해당 카테고리를 유지한다. 빈 배열로 덮어쓰지 않는다
- `index.html`은 이번 작업에서 변경하지 않는다
- 작업 브랜치: `feature/naver-cluster-ranking`

## 파일 구조

| 파일 | 책임 |
|---|---|
| `news/__init__.py` | 빈 패키지 마커 |
| `news/rank.py` | 정규화·토큰화·유사도·클러스터링·채점·선출. **네트워크 없음** |
| `news/sources.py` | 구글 RSS 및 네이버 API 호출과 파싱. 외부 호출 전부 |
| `news/history.py` | `seen_history.json` 읽기·기록·정리 |
| `fetch_news.py` | 카테고리 설정 + 오케스트레이션 + 저장 |
| `tools/measure_rotation.py` | git 이력에서 회전율 측정 |
| `tests/test_rank.py` | `rank.py` 단위 테스트 |
| `tests/test_sources.py` | 파싱 테스트 (고정 픽스처, 네트워크 없음) |
| `tests/test_history.py` | 이력 파일 테스트 |
| `requirements-dev.txt` | `requests`, `pytest` |

---

### Task 1: 개발 환경과 링크 정규화

**Files:**
- Create: `requirements-dev.txt`
- Create: `news/__init__.py`
- Create: `news/rank.py`
- Create: `tests/test_rank.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces: `news.rank.link_key(url: str) -> str`

- [ ] **Step 1: 개발 환경 구성**

```bash
cd ~/Desktop/ClaudeWork/news-app
git checkout feature/naver-cluster-ranking
python3 -m venv .venv
.venv/bin/pip install --quiet requests pytest
printf 'requests\npytest\n' > requirements-dev.txt
printf '.venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n' > .gitignore
mkdir -p news tests tools
touch news/__init__.py
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_rank.py`:

```python
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
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: FAIL — `ImportError: cannot import name 'link_key'`

- [ ] **Step 4: 최소 구현**

`news/rank.py`:

```python
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
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 커밋**

```bash
git add requirements-dev.txt .gitignore news/ tests/
git commit -m "feat: 링크 정규화 — 추적 파라미터만 제거하고 기사 ID 보존"
```

---

### Task 2: 제목 정제와 유사도 판정

**Files:**
- Modify: `news/rank.py`
- Modify: `tests/test_rank.py`

**Interfaces:**
- Consumes: `link_key`
- Produces:
  - `clean_title(raw: str) -> str`
  - `content_words(title: str) -> list[str]`
  - `title_tokens(title: str) -> set[str]`
  - `is_similar(a: set[str], b: set[str]) -> bool`
  - `verification_query(title: str, max_tokens: int = 4) -> str`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_rank.py` 하단에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: FAIL — `ImportError: cannot import name 'clean_title'`

- [ ] **Step 3: 구현 추가**

`news/rank.py` 상단 import에 추가: `import html`, `import re`

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: 커밋**

```bash
git add news/rank.py tests/test_rank.py
git commit -m "feat: 제목 정제·토큰화·유사도 판정"
```

---

### Task 3: 데이터 구조와 클러스터링

**Files:**
- Modify: `news/rank.py`
- Modify: `tests/test_rank.py`

**Interfaces:**
- Consumes: `title_tokens`, `is_similar`
- Produces:
  - `Article` dataclass: `title, link, key, published, outlet, origin, rank`
  - `Cluster` dataclass: `articles: list[Article]`, `naver_matches: int | None = None`
    - properties: `origins -> set[str]`, `outlet_count -> int`, `best_rank -> int`, `newest -> datetime`
  - `cluster_articles(articles: list[Article]) -> list[Cluster]`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_rank.py` 하단에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: FAIL — `ImportError: cannot import name 'Article'`

- [ ] **Step 3: 구현 추가**

`news/rank.py` import에 추가: `from dataclasses import dataclass, field`

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: PASS (17 passed)

- [ ] **Step 5: 커밋**

```bash
git add news/rank.py tests/test_rank.py
git commit -m "feat: Article/Cluster 데이터 구조와 사건 클러스터링"
```

---

### Task 4: 채점 함수

**Files:**
- Modify: `news/rank.py`
- Modify: `tests/test_rank.py`

**Interfaces:**
- Consumes: `Cluster`
- Produces:
  - `freshness_score(newest: datetime, now: datetime) -> float`
  - `cross_score(cluster: Cluster) -> float`
  - `rank_score(cluster: Cluster) -> float`
  - `outlet_score(cluster: Cluster) -> float`
  - `importance_score(cluster: Cluster) -> float`
  - `history_penalty(count: int) -> float`
  - 상수: `HALF_LIFE_HOURS = 6.0`, `PENALTY_PER_EXPOSURE = 12.0`, `PENALTY_CAP = 60.0`, `NAVER_MATCH_THRESHOLD = 3`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_rank.py` 하단에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: FAIL — `ImportError: cannot import name 'freshness_score'`

- [ ] **Step 3: 구현 추가**

`news/rank.py`에 추가:

```python
HALF_LIFE_HOURS = 6.0
PENALTY_PER_EXPOSURE = 12.0
PENALTY_CAP = 60.0
NAVER_MATCH_THRESHOLD = 3

CROSS_WEIGHT = 40.0
RANK_WEIGHT = 35.0
OUTLET_WEIGHT = 25.0
RANK_POOL = 20.0
OUTLET_CAP = 4


def freshness_score(newest, now):
    """반감기 6시간의 지수 감쇠. 0~100."""
    age_hours = max(0.0, (now - newest).total_seconds() / 3600.0)
    return 100.0 * (0.5 ** (age_hours / HALF_LIFE_HOURS))


def cross_score(cluster):
    """양쪽 소스에 다 있으면 만점. cat-etc는 네이버 유사 기사 수로 판정한다."""
    if cluster.naver_matches is not None:
        return CROSS_WEIGHT if cluster.naver_matches >= NAVER_MATCH_THRESHOLD else 0.0
    return CROSS_WEIGHT if {'google', 'naver'} <= cluster.origins else 0.0


def rank_score(cluster):
    return max(0.0, RANK_WEIGHT * (1.0 - cluster.best_rank / RANK_POOL))


def outlet_score(cluster):
    steps = min(max(cluster.outlet_count - 1, 0), OUTLET_CAP)
    return OUTLET_WEIGHT * steps / OUTLET_CAP


def importance_score(cluster):
    return cross_score(cluster) + rank_score(cluster) + outlet_score(cluster)


def history_penalty(count):
    return min(count * PENALTY_PER_EXPOSURE, PENALTY_CAP)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: PASS (25 passed)

- [ ] **Step 5: 커밋**

```bash
git add news/rank.py tests/test_rank.py
git commit -m "feat: 신선도·중요도·이력감점 채점 함수"
```

---

### Task 5: 대표 선출과 상위 N 선택

**Files:**
- Modify: `news/rank.py`
- Modify: `tests/test_rank.py`

**Interfaces:**
- Consumes: `Cluster`, `freshness_score`, `importance_score`, `history_penalty`
- Produces:
  - `pick_representative(cluster: Cluster, history: dict[str, int]) -> Article`
  - `total_score(cluster: Cluster, now: datetime, history: dict[str, int]) -> float`
  - `select_top(clusters: list[Cluster], now: datetime, history: dict[str, int], max_items: int) -> list[Article]`

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_rank.py` 하단에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: FAIL — `ImportError: cannot import name 'pick_representative'`

- [ ] **Step 3: 구현 추가**

`news/rank.py`에 추가:

```python
def pick_representative(cluster, history):
    """이력 적은 것 → 최신 → 네이버 원문 링크 순으로 고른다."""
    def sort_key(article):
        return (
            history.get(article.key, 0),
            -article.published.timestamp(),
            0 if article.origin == 'naver' else 1,
        )
    return min(cluster.articles, key=sort_key)


def total_score(cluster, now, history):
    """0.5 × 신선도 + 0.5 × 중요도 − 대표 기사의 노출 이력 감점."""
    representative = pick_representative(cluster, history)
    exposures = history.get(representative.key, 0)
    return (
        0.5 * freshness_score(cluster.newest, now)
        + 0.5 * importance_score(cluster)
        - history_penalty(exposures)
    )


def select_top(clusters, now, history, max_items):
    """점수 높은 순으로 max_items개 클러스터의 대표 기사를 반환한다."""
    ranked = sorted(clusters, key=lambda c: -total_score(c, now, history))
    return [pick_representative(c, history) for c in ranked[:max_items]]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_rank.py -v`
Expected: PASS (32 passed)

- [ ] **Step 5: 커밋**

```bash
git add news/rank.py tests/test_rank.py
git commit -m "feat: 대표 기사 선출과 상위 N 선택 + 회귀 시나리오 테스트"
```

---

### Task 6: 노출 이력 저장

**Files:**
- Create: `news/history.py`
- Create: `tests/test_history.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `load(path: str) -> dict[str, dict]`
  - `counts(raw: dict) -> dict[str, int]`
  - `record(raw: dict, keys: Iterable[str], now: datetime) -> dict`
  - `prune(raw: dict, now: datetime, retention_hours: int = 48) -> dict`
  - `save(raw: dict, path: str) -> None`
  - 상수: `HISTORY_PATH = 'seen_history.json'`, `RETENTION_HOURS = 48`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_history.py`:

```python
import json
from datetime import datetime, timedelta, timezone

from news import history

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def test_load_returns_empty_dict_when_missing(tmp_path):
    assert history.load(str(tmp_path / 'nope.json')) == {}


def test_load_returns_empty_dict_on_corrupt_file(tmp_path):
    path = tmp_path / 'broken.json'
    path.write_text('{not json', encoding='utf-8')
    assert history.load(str(path)) == {}


def test_record_increments_count():
    raw = {}
    raw = history.record(raw, ['https://a.com/1'], NOW)
    raw = history.record(raw, ['https://a.com/1'], NOW)
    assert raw['https://a.com/1']['count'] == 2


def test_counts_extracts_ints():
    raw = {'https://a.com/1': {'count': 3, 'last': '2026-08-11T12:00:00Z'}}
    assert history.counts(raw) == {'https://a.com/1': 3}


def test_prune_drops_entries_older_than_retention():
    old = (NOW - timedelta(hours=49)).strftime('%Y-%m-%dT%H:%M:%SZ')
    recent = (NOW - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
    raw = {
        'https://a.com/old': {'count': 5, 'last': old},
        'https://a.com/new': {'count': 1, 'last': recent},
    }
    kept = history.prune(raw, NOW)
    assert 'https://a.com/old' not in kept
    assert 'https://a.com/new' in kept


def test_prune_drops_malformed_entries():
    raw = {'https://a.com/bad': {'count': 1, 'last': 'garbage'}}
    assert history.prune(raw, NOW) == {}


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / 'seen.json')
    raw = history.record({}, ['https://a.com/1'], NOW)
    history.save(raw, path)
    assert history.load(path) == raw
    assert json.loads((tmp_path / 'seen.json').read_text(encoding='utf-8'))
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news.history'`

- [ ] **Step 3: 구현**

`news/history.py`:

```python
"""노출 이력 파일 관리. 기사 링크(정규화 키) 기준으로 노출 횟수를 센다."""
import json
from datetime import datetime, timedelta, timezone

HISTORY_PATH = 'seen_history.json'
RETENTION_HOURS = 48
_STAMP = '%Y-%m-%dT%H:%M:%SZ'


def load(path=HISTORY_PATH):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def counts(raw):
    return {k: v.get('count', 0) for k, v in raw.items() if isinstance(v, dict)}


def record(raw, keys, now):
    stamp = now.strftime(_STAMP)
    for key in keys:
        entry = raw.setdefault(key, {'count': 0, 'last': stamp})
        entry['count'] = entry.get('count', 0) + 1
        entry['last'] = stamp
    return raw


def prune(raw, now, retention_hours=RETENTION_HOURS):
    cutoff = now - timedelta(hours=retention_hours)
    kept = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            last = datetime.strptime(value['last'], _STAMP).replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if last >= cutoff:
            kept[key] = value
    return kept


def save(raw, path=HISTORY_PATH):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False, indent=2, sort_keys=True)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (39 passed)

- [ ] **Step 5: 커밋**

```bash
git add news/history.py tests/test_history.py
git commit -m "feat: 노출 이력 저장·정리 (48시간 보관)"
```

---

### Task 7: 구글 소스

**Files:**
- Create: `news/sources.py`
- Create: `tests/test_sources.py`
- Create: `tests/fixtures/google_search.xml`
- Create: `tests/fixtures/google_top.xml`

**Interfaces:**
- Consumes: `news.rank.Article`, `link_key`, `clean_title`
- Produces:
  - `parse_pubdate(raw: str) -> datetime | None`
  - `parse_google_rss(xml_bytes: bytes, limit: int = 20) -> list[Article]`
  - `fetch_google_search(query: str, limit: int = 20) -> list[Article]`
  - `fetch_google_top_stories(limit: int = 20) -> list[Article]`

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/google_search.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>서울 집값 1년 만에 15% 급등 - 매일일보</title>
  <link>https://www.mdilbo.com/detail/abc?utm_source=googlenews</link>
  <pubDate>Tue, 11 Aug 2026 06:14:03 GMT</pubDate>
  <source url="https://www.mdilbo.com">매일일보</source>
</item>
<item>
  <title>전세가율보다 무서운 건 낙찰가율이다 - 네이버프리미엄</title>
  <guid isPermaLink="false">CBMiXWh0dHBz</guid>
  <pubDate>Mon, 10 Aug 2026 23:55:00 GMT</pubDate>
  <source url="https://contents.premium.naver.com">네이버프리미엄</source>
</item>
<item>
  <title>날짜없음 기사</title>
  <link>https://example.com/nodate</link>
  <pubDate></pubDate>
  <source url="https://example.com">예시신문</source>
</item>
</channel></rss>
```

`tests/fixtures/google_top.xml`: 같은 형식으로 item 2개 (`천안 교회 어린이 사망 사설 - 경향신문`, `이 대통령 세법개정안 구윤철에 지시 - 경향신문`). 링크는 `https://khan.co.kr/1`, `https://khan.co.kr/2`, pubDate는 각각 `Tue, 11 Aug 2026 09:48:00 GMT`, `Tue, 11 Aug 2026 07:25:00 GMT`.

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_sources.py`:

```python
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
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'news.sources'`

- [ ] **Step 4: 구현**

`news/sources.py`:

```python
"""외부 소스 호출과 파싱. 네트워크에 닿는 코드는 전부 이 파일에 있다."""
import os
import time
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

import requests

from news.rank import Article, clean_title, link_key

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}
TIMEOUT = 15


def parse_pubdate(raw):
    """RFC 2822 날짜를 UTC datetime으로. 실패하면 None."""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_google_rss(xml_bytes, limit=20):
    root = ET.fromstring(xml_bytes)
    articles = []
    for element in root.findall('.//item'):
        if len(articles) >= limit:
            break
        published = parse_pubdate(element.findtext('pubDate') or '')
        if published is None:
            continue
        raw_link = (element.findtext('link') or element.findtext('guid') or '').strip()
        if not raw_link:
            continue
        link = raw_link if raw_link.startswith('http') \
            else f'https://news.google.com/articles/{raw_link}'
        source = element.find('source')
        outlet = source.text.strip() if source is not None and source.text else ''
        articles.append(Article(
            title=clean_title(element.findtext('title') or ''),
            link=link,
            key=link_key(link),
            published=published,
            outlet=outlet,
            origin='google',
            rank=len(articles),
        ))
    return articles


def _get(url, params=None, headers=None):
    response = requests.get(url, params=params,
                            headers=headers or HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response


def fetch_google_search(query, limit=20):
    url = (f'https://news.google.com/rss/search?q={quote(query)}+when%3A1d'
           f'&hl=ko&gl=KR&ceid=KR:ko')
    return parse_google_rss(_get(url).content, limit)


def fetch_google_top_stories(limit=20):
    url = 'https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko'
    return parse_google_rss(_get(url).content, limit)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (46 passed)

- [ ] **Step 6: 커밋**

```bash
git add news/sources.py tests/test_sources.py tests/fixtures/
git commit -m "feat: 구글 RSS 수집·파싱"
```

---

### Task 8: 네이버 소스

**Files:**
- Modify: `news/sources.py`
- Modify: `tests/test_sources.py`
- Create: `tests/fixtures/naver_news.json`

**Interfaces:**
- Consumes: `news.rank.Article`, `link_key`, `clean_title`, `title_tokens`, `is_similar`, `verification_query`
- Produces:
  - `NaverCredentialsMissing` (Exception)
  - `parse_naver(payload: dict, limit: int = 20) -> list[Article]`
  - `fetch_naver_search(query: str, sort: str = 'sim', limit: int = 20) -> list[Article]`
  - `count_naver_matches(title: str, limit: int = 20) -> int`

- [ ] **Step 1: 픽스처 작성**

`tests/fixtures/naver_news.json`:

```json
{
  "items": [
    {
      "title": "서울 <b>집값</b> 1년 만에 15% 급등 &quot;규제 무색&quot;",
      "originallink": "https://www.mdilbo.com/detail/xyz",
      "link": "https://n.news.naver.com/mnews/article/001/000",
      "pubDate": "Tue, 11 Aug 2026 15:14:03 +0900"
    },
    {
      "title": "서울 집값 1년 만에 15% 뛰어",
      "originallink": "https://www.hankyung.com/article/111",
      "link": "https://n.news.naver.com/mnews/article/015/111",
      "pubDate": "Tue, 11 Aug 2026 14:00:00 +0900"
    },
    {
      "title": "무관한 스포츠 소식 어제의 경기 결과",
      "originallink": "https://sports.example.com/1",
      "link": "https://n.news.naver.com/mnews/article/999/1",
      "pubDate": "Tue, 11 Aug 2026 13:00:00 +0900"
    }
  ]
}
```

- [ ] **Step 2: 실패하는 테스트 추가**

`tests/test_sources.py` 하단에 추가:

```python
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
```

`tests/test_rank.py`가 아니라 여기에 검증 모드 테스트도 추가한다:

```python
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
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_naver'`

- [ ] **Step 4: 구현 추가**

`news/sources.py` import에 추가: `from news.rank import title_tokens, is_similar, verification_query`

```python
NAVER_ENDPOINT = 'https://openapi.naver.com/v1/search/news.json'
NAVER_RETRIES = 1


class NaverCredentialsMissing(RuntimeError):
    """NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없다."""


def _naver_headers():
    client_id = os.environ.get('NAVER_CLIENT_ID')
    client_secret = os.environ.get('NAVER_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise NaverCredentialsMissing(
            'NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정해야 한다')
    return {
        'X-Naver-Client-Id': client_id,
        'X-Naver-Client-Secret': client_secret,
        'Accept-Language': 'ko-KR,ko;q=0.9',
    }


def parse_naver(payload, limit=20):
    articles = []
    for item in payload.get('items', []):
        if len(articles) >= limit:
            break
        published = parse_pubdate(item.get('pubDate', ''))
        if published is None:
            continue
        link = (item.get('originallink') or item.get('link') or '').strip()
        if not link:
            continue
        outlet = urlsplit(link).netloc.lower()
        if outlet.startswith('www.'):
            outlet = outlet[4:]
        articles.append(Article(
            title=clean_title(item.get('title', '')),
            link=link,
            key=link_key(link),
            published=published,
            outlet=outlet,
            origin='naver',
            rank=len(articles),
        ))
    return articles


def fetch_naver_search(query, sort='sim', limit=20):
    """sort는 'sim'(정확도) 또는 'date'(최신). 429는 1회 재시도한다."""
    headers = _naver_headers()
    params = {'query': query, 'display': limit, 'sort': sort}
    for attempt in range(NAVER_RETRIES + 1):
        response = requests.get(NAVER_ENDPOINT, params=params,
                                headers=headers, timeout=TIMEOUT)
        if response.status_code == 429 and attempt < NAVER_RETRIES:
            time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        return parse_naver(response.json(), limit)
    return []


def count_naver_matches(title, limit=20):
    """cat-etc 검증용. 제목과 같은 사건을 다룬 네이버 기사 수를 센다."""
    query = verification_query(title)
    if not query:
        return 0
    tokens = title_tokens(title)
    found = fetch_naver_search(query, sort='sim', limit=limit)
    return sum(1 for a in found if is_similar(tokens, title_tokens(a.title)))
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (53 passed)

- [ ] **Step 6: 커밋**

```bash
git add news/sources.py tests/test_sources.py tests/fixtures/naver_news.json
git commit -m "feat: 네이버 뉴스 검색 수집 + cat-etc 검증 모드"
```

---

### Task 9: 오케스트레이션 재작성

**Files:**
- Modify: `fetch_news.py` (전체 교체)
- Create: `tests/test_fetch_news.py`

**Interfaces:**
- Consumes: `news.rank`, `news.sources`, `news.history` 전체
- Produces:
  - `CATEGORIES` (list[dict])
  - `build_category(cat: dict, now: datetime, history_counts: dict) -> tuple[list[Article] | None, list[str]]`
  - `to_json_items(articles: list[Article]) -> list[dict]`
  - `main() -> None`

`build_category`의 첫 번째 반환값이 `None`이면 "모든 소스 실패 — 이전 데이터 유지" 신호다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_fetch_news.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_fetch_news.py -v`
Expected: FAIL — `AttributeError: module 'fetch_news' has no attribute 'to_json_items'`

- [ ] **Step 3: `fetch_news.py` 전체 교체**

```python
"""카테고리별 뉴스를 수집해 news_data.json으로 저장한다."""
import json
from datetime import datetime, timezone

from news import history, rank, sources

DATA_PATH = 'news_data.json'

CATEGORIES = [
    {'id': 'cat-us', 'max_items': 3, 'queries': [
        '나스닥 뉴욕증시 S&P500',
        '연준 금리 미국 경제지표',
        '엔비디아 테슬라 애플 빅테크',
    ]},
    {'id': 'cat-kr', 'max_items': 3, 'queries': [
        '코스피 코스닥 주식시장',
        '삼성전자 반도체 실적 국내증시',
    ]},
    {'id': 'cat-coin', 'max_items': 3, 'queries': [
        '비트코인 이더리움 시세',
        '암호화폐 규제 거래소 알트코인',
    ]},
    {'id': 'cat-land', 'max_items': 3, 'queries': [
        '부동산 아파트 매매가격',
        '전세 청약 분양 부동산정책',
    ]},
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (57 passed)

- [ ] **Step 5: 커밋**

```bash
git add fetch_news.py tests/test_fetch_news.py
git commit -m "feat: 오케스트레이션 재작성 — degraded 기록과 이전 데이터 보존"
```

---

### Task 10: 회전율 측정 도구

**Files:**
- Create: `tools/measure_rotation.py`

**Interfaces:**
- Consumes: 없음 (git 이력만 읽는다)
- Produces: CLI. `python3 tools/measure_rotation.py [--since ISO8601]`

- [ ] **Step 1: 구현**

`tools/measure_rotation.py`:

```python
"""git 커밋 이력에서 카테고리별 뉴스 회전율을 측정한다.

사용: python3 tools/measure_rotation.py --since 2026-08-11T00:00:00+09:00
"""
import argparse
import json
import subprocess
from collections import defaultdict

CATEGORIES = ['cat-us', 'cat-kr', 'cat-coin', 'cat-land', 'cat-etc']


def commits_since(since):
    out = subprocess.run(
        ['git', 'log', '--format=%H', f'--since={since}', '--', 'news_data.json'],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.split()


def snapshot(commit):
    out = subprocess.run(['git', 'show', f'{commit}:news_data.json'],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--since', default='24 hours ago')
    args = parser.parse_args()

    commits = commits_since(args.since)
    slots = defaultdict(int)
    unique = defaultdict(set)
    appearances = defaultdict(lambda: defaultdict(int))

    for commit in commits:
        data = snapshot(commit)
        if not data:
            continue
        for cat in CATEGORIES:
            for item in data.get(cat, []):
                link = item.get('link', '')
                slots[cat] += 1
                unique[cat].add(link)
                appearances[cat][link] += 1

    print(f'수집 실행 {len(commits)}회 기준 ({args.since})\n')
    print(f"{'카테고리':<10}{'슬롯':>7}{'고유':>7}{'회전율':>8}   최장 잔류")
    for cat in CATEGORIES:
        if not slots[cat]:
            print(f'{cat:<10}{"— 데이터 없음":>30}')
            continue
        rate = len(unique[cat]) / slots[cat] * 100
        top_link, top_count = max(appearances[cat].items(), key=lambda kv: kv[1])
        print(f'{cat:<10}{slots[cat]:>7}{len(unique[cat]):>7}{rate:>7.0f}%'
              f'   {top_count}회  {top_link[:48]}')


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 기준선 측정 (배포 전)**

Run: `python3 tools/measure_rotation.py --since "2026-08-11T00:00:00+09:00"`
Expected: cat-us 28% 내외, cat-coin 32% 내외 — 스펙 §1의 표와 일치해야 한다. 어긋나면 도구가 틀린 것이니 고친다.

- [ ] **Step 3: 커밋**

```bash
git add tools/measure_rotation.py
git commit -m "chore: 회전율 측정 도구"
```

---

### Task 11: 워크플로 연결과 실제 실행 검증

**Files:**
- Modify: `.github/workflows/fetch_news.yml`
- Delete: `fetch_news.yml` (루트의 추적되지 않는 중복 파일)

**Interfaces:**
- Consumes: 전체 파이프라인
- Produces: 배포 가능한 상태

**선행 조건:** `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET`가 저장소 Secrets에 등록되어 있어야 한다. 없으면 Step 2에서 네이버가 전부 실패하고 구글 단독 결과가 나온다 — 그것도 유효한 확인이지만 교차 검증은 검증되지 않는다.

- [ ] **Step 1: 워크플로 수정**

`.github/workflows/fetch_news.yml`의 `Fetch news` 스텝을 교체한다.

```yaml
      - name: Fetch news
        env:
          NAVER_CLIENT_ID: ${{ secrets.NAVER_CLIENT_ID }}
          NAVER_CLIENT_SECRET: ${{ secrets.NAVER_CLIENT_SECRET }}
        run: python3 fetch_news.py
```

`Commit and push` 스텝의 `git add`에 이력 파일을 추가한다.

```yaml
          git add news_data.json seen_history.json
```

- [ ] **Step 2: 로컬 실제 실행**

```bash
export NAVER_CLIENT_ID=<developers.naver.com에서 확인한 값>
export NAVER_CLIENT_SECRET=<확인한 값>
.venv/bin/python fetch_news.py
```

Expected: 5개 카테고리 모두 건수가 출력되고 `news_data.json`, `seen_history.json`이 갱신된다.

- [ ] **Step 3: 결과 육안 확인**

```bash
.venv/bin/python -c "
import json
d = json.load(open('news_data.json'))
print('degraded:', d.get('degraded', '없음'))
for k in ['cat-us','cat-kr','cat-coin','cat-land','cat-etc']:
    print(f'--- {k}')
    for it in d[k]:
        print('   ', it['pubDate'], '|', it['source'], '|', it['title'][:50])
"
```

확인할 것:
- `degraded`가 비어 있는가 (네이버 인증이 통했는가)
- 각 카테고리 건수가 맞는가 (cat-etc는 5, 나머지 3)
- 발행 시각이 대부분 몇 시간 이내인가
- 사설·칼럼이 cat-etc 상위에 있지 않은가
- 링크를 몇 개 눌러 404가 아닌지 확인

- [ ] **Step 4: 전체 테스트 재실행**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (57 passed)

- [ ] **Step 5: 커밋하고 main 병합**

```bash
git rm --cached fetch_news.yml 2>/dev/null || true
rm -f fetch_news.yml
git add .github/workflows/fetch_news.yml news_data.json seen_history.json
git commit -m "feat: 워크플로에 네이버 인증 연결"
git checkout main && git pull --ff-only origin main
git merge feature/naver-cluster-ranking
```

- [ ] **Step 6: 배포 후 24시간 뒤 검증**

Run: `python3 tools/measure_rotation.py --since "24 hours ago"`

스펙 §2 성공 기준과 대조한다.

| 지표 | 목표 |
|---|---|
| 회전율 (cat-etc 제외 4개) | 60% 이상 |
| 최장 잔류 (동일 링크) | 5회 이하 |
| cat-etc 회전율 | 62% 유지 |

미달이면 `HALF_LIFE_HOURS`, `PENALTY_PER_EXPOSURE`, `NAVER_MATCH_THRESHOLD`를 조정하고 회귀 테스트를 다시 돌린다.

---

## 자체 검토 결과

**스펙 커버리지**

| 스펙 섹션 | 담당 태스크 |
|---|---|
| §3 소스 전략 (5개 카테고리 구글+네이버) | 7, 8, 9 |
| §3 cat-etc 검증자 방식 | 8 (`count_naver_matches`), 9 (`_annotate_naver_matches`) |
| §4 구조 (네트워크/순수 분리) | 1~9 전체 |
| §4 outlet 형식 불일치 | 3 (`outlet_count`) |
| §5 신선도·중요도·총점 | 4 |
| §5 이력은 링크 기준 | 5, 6 |
| §5 대표 선출 | 5 |
| §6 예외 처리 (degraded, 이전 데이터 유지) | 9 |
| §7 이력 파일·48시간 정리 | 6 |
| §7 링크 정규화 | 1 |
| §8 테스트 | 각 태스크에 분산 |
| §9 검증 | 10 |
| §10 배포 | 11 |

**남은 위험**

- 네이버 검색 결과의 실제 품질(관련성, 국내 매체 커버리지)은 Task 11 이전에는 알 수 없다. 픽스처 테스트는 파싱만 검증한다
- `NAVER_MATCH_THRESHOLD = 3`은 근거 없는 초기값이다. Task 11 Step 6에서 조정한다
- cat-etc의 네이버 검증은 클러스터당 1회 호출이라, Top Stories 20건이 20개 클러스터로 쪼개지면 20회가 된다. 스펙의 호출량 추정과 일치한다
