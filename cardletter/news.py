from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import html
import re
from urllib.parse import urlencode, urlsplit, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from .rankings import Roster


@dataclass(frozen=True)
class Feed:
    name: str
    query: str
    official_domain: str = ""


# MOLIT currently uses indexed search; FSC/FSS use public official board lists below.
FEEDS = (
    Feed("국토교통부", 'site:molit.go.kr (주택 OR 건설 OR 부동산)', "molit.go.kr"),
    Feed("한국투자캐피탈", '"한국투자캐피탈"'),
    Feed("부동산 PF·금융", '"부동산" (PF OR 프로젝트파이낸싱 OR 금융 OR 대출)'),
    # Do not put sports exclusions in the search itself: indexed sidebars can hide legitimate finance stories.
    # Business/company validation happens on each returned headline below.
    Feed("기업금융·IB", '금융 (인수금융 OR 기업대출 OR 구조화금융 OR NPL)'),
    Feed("투자·신기술금융", '캐피탈 (신기술금융 OR 지분투자 OR 펀드)'),
    Feed("리스크관리", '금융 (연체율 OR 충당금 OR 건전성)'),
    Feed("IT·디지털", '금융 (정보보호 OR 해킹 OR 전자금융 OR 인공지능)'),
    Feed("캐피탈업권", '캐피탈 OR 현대커머셜'),
    Feed("개인·리테일 금융", '개인대출 OR 가계대출 OR 자동차금융 OR 오토리스 OR 할부금융 OR 금융소비자'),
)

OFFICIAL_BOARDS = (
    ("금융위원회", "https://www.fsc.go.kr/no010101", "li", r"/no010101/\d+[^\"]*"),
    ("금융감독원", "https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218",
     "tr", r"/fss/bbs/B0000188/view\.do\?[^\"]*"),
)
SOURCE_NAMES = tuple(b[0] for b in OFFICIAL_BOARDS) + tuple(f.name for f in FEEDS) + ("TOP100 시공사",)


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    publisher: str
    published: datetime
    feed: str
    official: bool = False
    date_only: bool = False
    source_url: str = ""


@dataclass(frozen=True)
class Coverage:
    name: str
    ok: bool
    count: int
    detail: str = ""
    method: str = "검색"


@dataclass(frozen=True)
class Card:
    article: Article
    category: str
    checkpoint: str
    score: int
    summary: str = ""
    summary_kind: str = "확인 불가"
    summary_url: str = ""
    summary_detail: str = ""
    contractors: tuple[str, ...] = ()
    contractor_ranks: tuple[int, ...] = ()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", value))).strip()


def https_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.hostname) and not parts.username


def parse_feed(data: bytes, feed: Feed) -> list[Article]:
    root = ET.fromstring(data)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("RSS 응답 형식이 아닙니다")
    articles = []
    for item in root.findall("./channel/item"):
        source = item.find("source")
        publisher = clean_text(source.text or "") if source is not None else "출처 미표기"
        title = clean_text(item.findtext("title", ""))
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(publisher) - 3].strip()
        link = item.findtext("link", "").strip()
        # Never render arbitrary schemes from external feeds as clickable links.
        if not title or not https_url(link):
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        source_host = urlsplit(source.get("url", "")).hostname if source is not None else ""
        official = bool(feed.official_domain and source_host and (
            source_host == feed.official_domain or source_host.endswith("." + feed.official_domain)
        ))
        # A site: query alone is not proof that the publisher is the agency.
        if feed.official_domain and not official:
            continue
        source_url = source.get("url", "") if source is not None else ""
        articles.append(Article(title, link, publisher, published, feed.name, official, source_url=source_url))
    return articles


def fetch_feed(feed: Feed, hours: int) -> tuple[list[Article], Coverage]:
    days = max(1, (hours + 23) // 24)
    url = "https://news.google.com/rss/search?" + urlencode({
        "q": feed.query + f" when:{days}d", "hl": "ko", "gl": "KR", "ceid": "KR:ko",
    })
    request = Request(url, headers={"User-Agent": "PublicFinanceCardletter/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            if urlsplit(response.url).hostname != "news.google.com":
                raise ValueError("예상하지 않은 RSS 응답 도메인")
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("RSS 크기 제한 초과")
        articles = parse_feed(data, feed)
        return articles, Coverage(feed.name, True, len(articles))
    except Exception as exc:
        # No raw error URLs, environment values, or credentials in generated outputs.
        detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        return [], Coverage(feed.name, False, 0, detail)


def parse_official(data: bytes, board: tuple) -> list[Article]:
    name, url, tag, link_pattern = board
    text = data.decode("utf-8")
    articles = []
    # Row-scoped parsing matches the currently verified public board structures.
    # Missing rows are a parser failure, never a successful "no announcements" result.
    for block in re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", text, re.S | re.I):
        link = re.search(rf'<a\b[^>]*href="({link_pattern})"[^>]*>(.*?)</a>', block, re.S | re.I)
        if not link:
            continue
        date = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", block)
        if not date:
            continue
        target = urljoin(url, html.unescape(link.group(1)))
        if not https_url(target) or urlsplit(target).hostname != urlsplit(url).hostname:
            continue
        title = clean_text(link.group(2))
        if not title:
            continue
        published = datetime.strptime(date.group(1), "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Seoul"))
        articles.append(Article(title, target, name, published, name, True, True, url))
    if not articles:
        raise ValueError("공식 게시판 목록을 파싱할 수 없습니다")
    return articles


def fetch_official(board: tuple) -> tuple[list[Article], Coverage]:
    name, url, _, _ = board
    try:
        request = Request(url, headers={"User-Agent": "PublicFinanceCardletter/0.1"})
        with urlopen(request, timeout=20) as response:
            if urlsplit(response.url).hostname != urlsplit(url).hostname:
                raise ValueError("예상하지 않은 공식 게시판 응답 도메인")
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("공식 게시판 크기 제한 초과")
        articles = parse_official(data, board)
        return articles, Coverage(name, True, len(articles), "최신 목록 첫 페이지; 게시 시각 미제공", "게시판")
    except Exception as exc:
        detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        return [], Coverage(name, False, 0, detail, "게시판")


def collect(hours: int, roster: Roster | None = None) -> tuple[list[Article], list[Coverage]]:
    if roster and roster.demo:
        raise ValueError("가상 순위 명단은 실제 뉴스 수집에 사용할 수 없습니다")
    with ThreadPoolExecutor(max_workers=4) as executor:
        official = [executor.submit(fetch_official, board) for board in OFFICIAL_BOARDS]
        feeds = [executor.submit(fetch_feed, feed, hours) for feed in FEEDS]
        results = [future.result() for future in official + feeds]
        if roster:
            queries = roster.queries()
            jobs = [executor.submit(fetch_feed, Feed("TOP100 시공사", q), hours) for q in queries]
            contractor_results = [future.result() for future in jobs]
            matched = [a for articles, _ in contractor_results for a in articles if roster.matches(a.title)]
            failures = sum(not c.ok for _, c in contractor_results)
            results.append((matched, Coverage("TOP100 시공사", failures == 0, len(matched),
                            f"{roster.year}년 100개사; {len(queries)}개 검색 중 실패 {failures}개")))
        else:
            results.append(([], Coverage("TOP100 시공사", False, 0, "공식 명단 확인 대기")))
    return [a for articles, _ in results for a in articles], [c for _, c in results]


CAPITAL_COMPANIES = (
    "한국투자캐피탈", "현대캐피탈", "KB캐피탈", "하나캐피탈", "우리금융캐피탈", "신한캐피탈",
    "NH농협캐피탈", "BNK캐피탈", "DGB캐피탈", "iM캐피탈", "IBK캐피탈", "롯데캐피탈",
    "미래에셋캐피탈", "메리츠캐피탈", "JB우리캐피탈", "한국캐피탈", "효성캐피탈",
    "애큐온캐피탈", "키움캐피탈", "현대커머셜", "산은캐피탈", "오릭스캐피탈", "BMW파이낸셜",
    "농협캐피탈", "우리캐피탈",
)
SPORTS = ("허수봉", "V리그", "v-리그", "토토", "프로골프", "골프대회", "e스포츠")
FINANCE = ("금융", "대출", "PF", "pf", "실적", "연체", "조달", "신용", "회사채", "유동성",
           "인수", "투자", "대표", "지배구조", "건전성", "금리", "리스", "할부", "수익", "자산",
           "이사회", "디지털", "경영", "전략", "연임", "로드맵")


def sports_news(title: str) -> bool:
    lower = title.lower()
    # 배구 is part of 지배구조: substring exclusion would hide genuine capital-company governance news.
    return bool(re.search(r"(?<![가-힣])(?:프로|남자|여자|대학|전국)?(?:배구|농구)", title)) or any(
        word.lower() in lower for word in SPORTS
    )


def is_capital_news(title: str) -> bool:
    lower = title.lower()
    if sports_news(title) or any(w in lower for w in ("캐피탈 원", "캐피탈원", "벤처캐피탈", "캐피털 원")):
        return False
    company = any(name.lower() in lower for name in CAPITAL_COMPANIES)
    industry = "캐피탈사" in title or "캐피탈 업계" in title or "캐피탈업계" in title
    return (company or industry) and any(w.lower() in lower for w in FINANCE)


def classify(article: Article, roster: Roster | None = None) -> tuple[str, str, int] | None:
    title = article.title.lower()
    # Rule-based business checkpoints are prompts for review, not article summaries.
    if sports_news(article.title):
        return None
    if roster and roster.matches(article.title) and any(w.lower() in title for w in (
        "수주", "PF", "신용", "부실", "유동성", "실적", "안전", "사고", "분양", "경영", "인사", "대표", "착공", "정비사업",
    )):
        return "TOP100 시공사", "시공사 경영·신용·수주·안전 관련 주요 변화를 확인하세요.", 115
    if any(word in title for word in (
        "개인대출", "가계대출", "신용대출", "주택담보대출", "주담대", "전세대출",
        "자동차금융", "자동차 금융", "오토리스", "할부금융", "할부 금융", "리테일금융",
        "리테일 금융", "금융소비자", "금융 소비자", "개인 금융", "개인금융",
    )) or (any(word in title for word in ("리스", "할부")) and
           any(word in title for word in ("자동차", "차량", "캐피탈", "금융"))):
        return "개인·리테일 금융", "개인 여신·자동차금융·소비자 보호 제도와 시장 변화를 확인하세요.", 100
    if is_capital_news(article.title) or (article.official and "캐피탈" in title and any(w.lower() in title for w in FINANCE)):
        return "캐피탈업권", "캐피탈사 건전성·조달·실적·경영 동향을 확인하세요.", 150 if "한국투자캐피탈" in title else 105
    if any(word in title for word in ("시공사", "건설사", "건설", "워크아웃")) and any(
        word in title for word in ("pf", "부실", "유동성", "신용", "워크아웃", "연체", "법정관리")
    ):
        return "시공사·신용", "시공사 신용과 사업 진행 이슈가 PF 검토 항목에 해당하는지 확인하세요.", 110
    if any(word in title for word in ("pf", "프로젝트파이낸싱")):
        return "부동산 PF", "사업성·상환재원·담보 및 부동산 금융 심사에 적용할 변화가 있는지 확인하세요.", 120
    if "부동산" in title and any(word in title for word in ("금융", "대출", "담보", "조달")):
        return "부동산 금융", "담보가치·조달 여건과 부동산 금융 심사 기준의 변화를 확인하세요.", 115
    if any(word in title for word in ("해킹", "정보유출", "정보 유출", "보안", "전자금융", "디지털", "인공지능")) and any(word in title for word in ("금융", "은행", "캐피탈", "여전")):
        return "IT·디지털", "외부 접점·접근권한·고객 안내와 관련 당국 조치를 원문에서 확인하세요.", 95
    if any(word in title for word in ("인수금융", "기업금융", "기업대출", "구조화금융", "npl")):
        return "기업금융·IB", "거래 구조·상환재원·신용보강 조건의 변화를 원문에서 확인하세요.", 95
    if any(word in title for word in ("신기술금융", "지분투자", "펀드")) and any(word in title for word in ("금융", "캐피탈", "투자")):
        return "투자", "투자 대상·회수 계획·손실 부담 조건을 원문에서 확인하세요.", 85
    if any(word in title for word in ("연체", "충당금", "건전성")) and any(word in title for word in ("금융", "은행", "캐피탈", "여전")):
        return "리스크관리", "지표의 기준일·대상 업권·비교 기간을 원문에서 확인하세요.", 90
    if article.official and any(word in title for word in ("금융", "규제", "정책", "건설")):
        return "정책·감독", "시행일·적용 대상·유예 기간과 여신전문금융회사 해당 여부를 원문에서 확인하세요.", 90
    if any(word in title for word in ("부동산", "주택", "미분양")):
        return "부동산 시장", "공급·분양 동향이 개발사업 사업성 검토에 참고할 변화인지 확인하세요.", 70
    return None


def normalized_title(title: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", title.lower())


def select(articles: list[Article], as_of: datetime, hours: int, limit: int = 6,
           roster: Roster | None = None, detailed: bool = False) -> list[Card]:
    candidates = []
    cutoff = as_of - timedelta(hours=hours)
    for article in articles:
        if article.date_only:
            # Date-only official posts overlap the reporting window by calendar date.
            in_window = cutoff.date() <= article.published.date() <= as_of.date()
        else:
            in_window = cutoff <= article.published <= as_of
        if not in_window:
            continue
        match = classify(article, roster)
        if match is None:
            continue
        category, checkpoint, weight = match
        age_hours = (as_of - article.published).total_seconds() / 3600
        score = weight + (20 if article.official else 0) + max(0, 12 - int(age_hours))
        matches = roster.matches(article.title) if roster and category == "TOP100 시공사" else ()
        candidates.append(Card(article, category, checkpoint, score,
                               contractors=tuple(c.name for c in matches), contractor_ranks=tuple(c.rank for c in matches)))
    candidates.sort(key=lambda c: (c.score, c.article.published), reverse=True)
    unique = []
    for card in candidates:
        title = normalized_title(card.article.title)
        if any(card.article.url == other.article.url or SequenceMatcher(
            None, title, normalized_title(other.article.title)
        ).ratio() >= 0.84 for other in unique):
            continue
        unique.append(card)
    if detailed:
        counts = {}
        result = []
        for card in unique:
            if counts.get(card.category, 0) < 3:
                result.append(card)
                counts[card.category] = counts.get(card.category, 0) + 1
            if len(result) >= limit:
                break
        return result
    # Fixed section budgets prevent construction/capital news from disappearing behind housing news.
    main = [c for c in unique if c.category not in ("TOP100 시공사", "캐피탈업권", "개인·리테일 금융", "기업금융·IB", "투자", "리스크관리", "IT·디지털")]
    primary = main[:1]
    official = next((c for c in main if c.article.official and c not in primary), None)
    if official:
        primary.append(official)
    elif len(main) > 1:
        primary.append(main[1])
    capital = [c for c in unique if c.category == "캐피탈업권"][:1]
    retail = [c for c in unique if c.category == "개인·리테일 금융"][:1]
    contractors = []
    for card in (c for c in unique if c.category == "TOP100 시공사"):
        if not any(set(card.contractors) & set(other.contractors) for other in contractors):
            contractors.append(card)
        if len(contractors) == 2:
            break
    return (primary + capital + retail + contractors)[:limit]


def to_record(card: Card) -> dict:
    result = asdict(card)
    result["article"]["published"] = card.article.published.isoformat()
    return result
