"""NAVER News Search API only; no Google RSS or institutional-board fallback."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from email.utils import parsedate_to_datetime
import json
import os
import re
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from bs4 import BeautifulSoup
from .news import Article, Coverage, clean_text
from .summaries import SourceRedirects, extract_summary, public_https

ENDPOINT = 'https://openapi.naver.com/v1/search/news.json'
QUERIES = (
    ('시공사', '건설사 부도'), ('시공사', '건설현장 사고'), ('시공사', '아파트 하자'),
    ('시공사', '시공사 공사현장'),
    ('수도권 부동산', '서울 부동산'), ('수도권 부동산', '경기 부동산'), ('수도권 부동산', '인천 부동산'),
    ('비수도권 부동산', '지방 미분양'), ('비수도권 부동산', '부산 부동산'),
    ('비수도권 부동산', '대구 부동산'), ('비수도권 부동산', '대전 부동산'), ('비수도권 부동산', '광주 부동산'),
    ('PF권역 주요뉴스', '부동산 PF'), ('PF권역 주요뉴스', '사업장 브리지론'),
)

PRESS = re.compile(r'보도\s*자료|press[ -]?release|뉴스와이어|자료\s*제공|업체\s*제공|홍보성\s*기사|유료\s*광고', re.I)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('NAVER API 리디렉션 거부')


def original_url(raw):
    try:
        u = urlsplit(raw)
        host = (u.hostname or '').lower()
        if host.endswith(('.naver.com', '.go.kr', '.gov')) or host in ('naver.com', 'news.naver.com') or any(x in host for x in ('newswire', 'prnewswire', 'businesswire')):
            return ''
        if u.scheme == 'http': u = u._replace(scheme='https')
        url = urlunsplit(u._replace(fragment=''))
        return url if public_https(url, url) else ''
    except (ValueError, TypeError):
        return ''


def parse_items(data, label):
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise ValueError('NAVER 응답 형식 오류')
    result = []
    for item in data['items']:
        if not isinstance(item, dict): continue
        if not all(isinstance(item.get(key, ''), str) for key in ('title', 'description', 'originallink', 'pubDate')): continue
        title = clean_text(item.get('title', ''))
        if not title or PRESS.search(title + ' ' + clean_text(item.get('description', ''))): continue
        url = original_url(item.get('originallink', ''))
        if not url: continue
        try:
            published = parsedate_to_datetime(item.get('pubDate', ''))
            if not published or published.tzinfo is None: continue
        except (ValueError, TypeError, OverflowError): continue
        host = urlsplit(url).hostname
        result.append(Article(title, url, host, published, label, source_url='https://' + host))
    return result


def collect(hours, roster=None):
    client_id, secret = os.getenv('NAVER_CLIENT_ID'), os.getenv('NAVER_CLIENT_SECRET')
    if not client_id or not secret:
        return [], [Coverage('NAVER 뉴스 API', False, 0, 'NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 설정 필요', 'API')]
    def fetch(pair):
        label, query = pair
        try:
            url = ENDPOINT + '?' + urlencode({'query': query, 'display': 100, 'start': 1, 'sort': 'date'})
            req = Request(url, headers={'X-Naver-Client-Id': client_id, 'X-Naver-Client-Secret': secret})
            with build_opener(NoRedirect()).open(req, timeout=20) as response:
                raw = response.read(3_000_001)
            if len(raw) > 3_000_000: raise ValueError('API 응답 크기 초과')
            articles = parse_items(json.loads(raw), label)
            return articles, Coverage('NAVER ' + label, True, len(articles), '검색 최신 100건/쿼리; 페이지 추가 조회 없음', 'API')
        except Exception as exc:
            reason = 'HTTP ' + str(exc.code) if isinstance(exc, HTTPError) else type(exc).__name__
            return [], Coverage('NAVER ' + label, False, 0, reason, 'API')
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, QUERIES))
    coverage = []
    for label in dict.fromkeys(label for label,_ in QUERIES):
        states = [state for (_,state), (group,_) in zip(results, QUERIES) if group == label]
        failed = [c.detail for c in states if not c.ok]
        coverage.append(Coverage('NAVER ' + label, not failed, sum(c.count for c in states), f'쿼리 {len(states)}개 · 실패 {len(failed)} · 최신 100건/쿼리' + (' · ' + ', '.join(failed) if failed else ''), 'API'))
    return [a for items,_ in results for a in items], coverage


def press_release(data, title):
    soup = BeautifulSoup(data, 'html.parser')
    metadata = [title]
    for meta in soup.select('meta[property="og:description"],meta[name="description"],meta[name="genre"],meta[property="article:section"]'):
        metadata.append(meta.get('content', ''))
    for node in soup.select('article, [itemprop="articleBody"], #article-view-content-div, #articleBody, #article_body, #article-body-content, #newsct_article, #dic_area, .article_body, .article-body'):
        for child in node.select('nav, footer, aside, script:not([type="application/ld+json"]), style, .copyright'): child.decompose()
        metadata.append(node.get_text(' ', strip=True)[:12000])
    for script in soup.find_all('script', type='application/ld+json'):
        try: metadata.append(json.dumps(json.loads(script.string or script.get_text()), ensure_ascii=False))
        except (ValueError, TypeError): pass
    return bool(PRESS.search(' '.join(metadata)))


def verify_card(card):
    url = original_url(card.article.url)
    if not url: return None, '원문 URL 없음/허용하지 않는 출처'
    try:
        opener = build_opener(SourceRedirects(card.article.source_url or url))
        with opener.open(Request(url, headers={'User-Agent': 'RealEstateDaily/1.0'}), timeout=12) as response:
            if response.status != 200: return None, '원문 HTTP 200 아님'
            if not public_https(response.geturl(), card.article.source_url or url): return None, '원문 도메인 불일치'
            if 'html' not in response.headers.get('Content-Type', '').lower(): return None, '원문 HTML 아님'
            final = response.geturl()
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000: return None, '원문 크기 초과'
        if press_release(raw, card.article.title): return None, '보도자료/홍보 표시'
        summary, kind = extract_summary(raw, card.article.title, limit=480)
        if not summary: return None, '기사 본문/제목 확인 실패'
        # Require an article-like title to reject soft-404 pages which return HTTP 200.
        soup = BeautifulSoup(raw, 'html.parser')
        node = soup.find('meta', property='og:title')
        page_title = clean_text(node.get('content', '')) if node else clean_text(soup.title.get_text() if soup.title else '')
        from difflib import SequenceMatcher
        from .news import normalized_title
        if not page_title or SequenceMatcher(None, normalized_title(page_title), normalized_title(card.article.title)).ratio() < .60:
            return None, '기사 제목 확인 실패'
        publisher = soup.find('meta', property='og:site_name')
        article = replace(card.article, url=final, publisher=clean_text(publisher.get('content', '')) if publisher and publisher.get('content') else card.article.publisher)
        return replace(card, article=article, summary=summary, summary_url=final, summary_kind=kind, summary_detail='원문 접속·기사 제목·보도자료 표시 검사 통과'), ''
    except Exception as exc:
        return None, 'HTTP ' + str(exc.code) if isinstance(exc, HTTPError) else type(exc).__name__


def verify(cards):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(verify_card, cards))
    from collections import Counter
    rejected = Counter(reason for card,reason in results if card is None)
    kept = [card for card,_ in results if card is not None]
    detail = '; '.join(f'{reason}: {count}' for reason,count in sorted(rejected.items()))
    return kept, Coverage('원문 검증', True, len(kept), f'검사 {len(cards)} / 제외 {len(cards)-len(kept)}' + (' · ' + detail if detail else ''), '원문 GET')
