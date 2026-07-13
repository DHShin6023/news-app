import re
import requests
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timezone
from urllib.parse import quote

# 카테고리별 서브 쿼리: 하나의 사건이 카테고리를 점령하지 못하도록
# 주제가 다른 쿼리 2~3개에서 골고루 뽑는다 (라운드로빈)
CATEGORIES = [
    {'id': 'cat-us', 'queries': [
        '나스닥 뉴욕증시 S&P500',
        '연준 금리 미국 경제지표',
        '엔비디아 테슬라 애플 빅테크',
    ]},
    {'id': 'cat-kr', 'queries': [
        '코스피 코스닥 주식시장',
        '삼성전자 반도체 실적 국내증시',
    ]},
    {'id': 'cat-coin', 'queries': [
        '비트코인 이더리움 시세',
        '암호화폐 규제 거래소 알트코인',
    ]},
    {'id': 'cat-land', 'queries': [
        '부동산 아파트 매매가격',
        '전세 청약 분양 부동산정책',
    ]},
    {'id': 'cat-etc', 'queries': None, 'max_items': 5},  # Top Stories 피드
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}


def title_tokens(title):
    """제목에서 비교용 토큰 추출 (말미의 '- 언론사' 제거, 특수문자 제거)"""
    t = re.sub(r'\s*-\s*[^-]+$', '', title)
    t = re.sub(r'[^0-9A-Za-z가-힣 ]', ' ', t)
    return {w for w in t.split() if len(w) >= 2}


def is_duplicate(tokens, seen_tokens_list):
    """기존 기사들과 제목 토큰 겹침이 크면 같은 사건으로 판정"""
    for seen in seen_tokens_list:
        if not tokens or not seen:
            continue
        inter = len(tokens & seen)
        jaccard = inter / len(tokens | seen)
        overlap = inter / min(len(tokens), len(seen))
        if jaccard >= 0.4 or overlap >= 0.6:
            return True
    return False


def fetch_feed(url, fetch_count=20):
    """RSS 피드를 Google 관련도 순서 그대로 파싱해서 반환"""
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for el in root.findall('.//item')[:fetch_count]:
        title = el.findtext('title') or ''
        link_raw = el.findtext('link') or el.findtext('guid') or ''
        if not link_raw:
            link = '#'
        elif link_raw.startswith('http'):
            link = link_raw
        else:
            link = f'https://news.google.com/articles/{link_raw}'
        pubdate = el.findtext('pubDate') or ''
        src_el = el.find('source')
        source = src_el.text.strip() if src_el is not None and src_el.text else ''
        items.append({'title': title, 'link': link, 'pubDate': pubdate, 'source': source})
    return items


def fetch_category(cat):
    max_items = cat.get('max_items', 3)
    try:
        if cat.get('queries'):
            feeds = []
            for q in cat['queries']:
                url = f"https://news.google.com/rss/search?q={quote(q)}+when%3A1d&hl=ko&gl=KR&ceid=KR:ko"
                try:
                    feeds.append(fetch_feed(url))
                except Exception as e:
                    print(f"  {cat['id']} 쿼리 '{q}' 오류: {e}")
                    feeds.append([])
        else:
            feeds = [fetch_feed("https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko")]

        # 라운드로빈: 각 쿼리에서 번갈아 1건씩, 중복 사건은 건너뛰며 선택
        selected = []
        seen_tokens = []
        seen_links = set()
        indices = [0] * len(feeds)
        while len(selected) < max_items:
            progressed = False
            for fi, feed in enumerate(feeds):
                if len(selected) >= max_items:
                    break
                while indices[fi] < len(feed):
                    item = feed[indices[fi]]
                    indices[fi] += 1
                    tokens = title_tokens(item['title'])
                    if len(tokens) < 3:  # 종목 시세 페이지 등 비기사 항목 제외
                        continue
                    if item['link'] in seen_links or is_duplicate(tokens, seen_tokens):
                        continue
                    selected.append(item)
                    seen_tokens.append(tokens)
                    seen_links.add(item['link'])
                    progressed = True
                    break
            if not progressed:
                break  # 모든 피드 소진

        print(f"  {cat['id']}: {len(selected)}개 선택 (쿼리 {len(feeds)}개, 중복 제거)")
        return selected
    except Exception as e:
        print(f"  {cat['id']} 오류: {e}")
        return []


result = {}
for cat in CATEGORIES:
    result[cat['id']] = fetch_category(cat)

result['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

with open('news_data.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"news_data.json 저장 완료 ({result['updated']})")
