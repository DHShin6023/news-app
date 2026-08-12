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
