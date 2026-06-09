import requests
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timezone
from urllib.parse import quote

CATEGORIES = [
    {'id': 'cat-us',   'query': '미국증시 나스닥 뉴욕증시'},
    {'id': 'cat-kr',   'query': '코스피 코스닥 주식시장'},
    {'id': 'cat-coin', 'query': '비트코인 이더리움 암호화폐'},
    {'id': 'cat-land', 'query': '부동산 아파트 매매가격'},
    {'id': 'cat-etc',  'query': None, 'max_items': 5},  # Top Stories 피드, 5개
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

def fetch_category(cat):
    if cat.get('query'):
        q = quote(cat['query'])
        url = f"https://news.google.com/rss/search?q={q}+when%3A1d&hl=ko&gl=KR&ceid=KR:ko"
    else:
        url = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"
    max_items = cat.get('max_items', 3)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for el in root.findall('.//item')[:max_items]:
            title   = el.findtext('title') or ''
            link_raw = el.findtext('link') or el.findtext('guid') or ''
            if not link_raw:
                link = '#'
            elif link_raw.startswith('http'):
                link = link_raw
            else:
                link = f'https://news.google.com/articles/{link_raw}'
            pubdate = el.findtext('pubDate') or ''
            src_el  = el.find('source')
            source  = src_el.text.strip() if src_el is not None and src_el.text else ''
            items.append({'title': title, 'link': link, 'pubDate': pubdate, 'source': source})
        print(f"  {cat['id']}: {len(items)}개 수집")
        return items
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
