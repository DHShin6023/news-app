"""git 커밋 이력에서 카테고리별 뉴스 회전율을 측정한다.

사용: python3 tools/measure_rotation.py --since 2026-08-11T00:00:00+09:00
"""
import argparse
import json
import subprocess
from collections import defaultdict

CATEGORIES = ['cat-us', 'cat-kr', 'cat-coin', 'cat-land', 'cat-etc']


def commits_since(since):
    # --full-history 필수. 기본 git log는 병합 커밋에서 한쪽 부모의 이력을 숨겨
    # (history simplification) 수집 실행분을 통째로 빠뜨린다.
    # 2026-08-12 병합 직후 실측: 기본 조회 9건 vs --full-history 30건
    out = subprocess.run(
        ['git', 'log', '--full-history', '--format=%H', f'--since={since}',
         '--', 'news_data.json'],
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
    unique_titles = defaultdict(set)
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
                unique_titles[cat].add(item.get('title', ''))
                appearances[cat][link] += 1

    print(f'수집 실행 {len(commits)}회 기준 ({args.since})\n')
    # 회전율은 링크 기준이 정본이다 (스펙 §2·§5: 노출 이력은 기사 링크 기준).
    # 제목 기준은 스펙 §1 기준선 표와 대조하기 위해 함께 출력한다 —
    # 같은 링크의 헤드라인만 바뀐 재노출을 새 기사로 세므로 항상 더 높게 나온다
    print(f"{'카테고리':<10}{'슬롯':>7}{'고유':>7}{'회전율':>8}{'(제목기준)':>11}   최장 잔류")
    for cat in CATEGORIES:
        if not slots[cat]:
            print(f'{cat:<10}{"— 데이터 없음":>30}')
            continue
        rate = len(unique[cat]) / slots[cat] * 100
        title_rate = len(unique_titles[cat]) / slots[cat] * 100
        top_link, top_count = max(appearances[cat].items(), key=lambda kv: kv[1])
        print(f'{cat:<10}{slots[cat]:>7}{len(unique[cat]):>7}{rate:>7.0f}%'
              f'{title_rate:>10.0f}%   {top_count}회  {top_link[:48]}')


if __name__ == '__main__':
    main()
