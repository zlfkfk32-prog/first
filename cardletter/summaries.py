"""Short extractive summaries from public publisher text, with explicit failures."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import ipaddress
import json
import re
from difflib import SequenceMatcher
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup
from googlenewsdecoder import gnews_decoder_async

from .news import Card, clean_text, normalized_title


def public_https(url: str, source_url: str) -> bool:
    try:
        target, source = urlsplit(url), urlsplit(source_url)
        port = target.port
    except ValueError:
        return False
    host = target.hostname or ""
    base = (source.hostname or "").removeprefix("www.")
    if target.scheme != "https" or not base or target.username or target.password or port not in (None, 443):
        return False
    if host != base and not host.endswith("." + base):
        return False
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host and bool(re.fullmatch(r"[A-Za-z0-9.-]+", host))


def brief(text: str, limit: int = 112) -> str:
    text = clean_text(text)
    text = re.sub(r"^.{0,55}?(?:기자\s*[=\]]|\]\s*|기자\s*=)\s*", "", text)
    sentences = re.split(r"(?<=[.!?])\s+(?=[가-힣A-Z\"‘“])", text)
    selected = []
    for sentence in sentences[:2]:
        if len(" ".join([*selected, sentence])) > limit:
            if not selected:
                selected.append(sentence[:limit - 1].rstrip() + "…")
            break
        selected.append(sentence)
    return " ".join(selected)


def extract_summary(data: bytes, title: str, limit: int = 112) -> tuple[str, str]:
    soup = BeautifulSoup(data, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    if re.search(r"Access Denied|Checking your browser|접근.{0,5}차단|로그인 후.{0,12}기사", page_text, re.I):
        return "", "원문 접근 제한"
    page_title_node = soup.find("meta", attrs={"property": "og:title"})
    page_title = page_title_node.get("content", "") if page_title_node else ""
    if page_title and SequenceMatcher(None, normalized_title(title), normalized_title(page_title)).ratio() < 0.35:
        return "", "기사 제목 불일치"
    bodies = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            value = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        def find_body(node):
            if isinstance(node, dict):
                if isinstance(node.get("articleBody"), str):
                    bodies.append(node["articleBody"])
                for child in node.values():
                    if isinstance(child, (dict, list)):
                        find_body(child)
            elif isinstance(node, list):
                for child in node:
                    find_body(child)
        find_body(value)
    selectors = (
        "[itemprop=articleBody]", "#article-view-content-div", "#articleBody", "#article_body",
        "#newsct_article", "#dic_area", "#article-body-content", "#cont_newstext", ".view_con_text",
        ".article-body", ".article_body", ".view_cont",
        ".board-view-cont", ".view-content", ".article_content", ".article-text", "article",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        for unwanted in node.select("script, style, nav, aside, footer, form, figure, figcaption, .copyright, .reporter, .ad"):
            unwanted.decompose()
        paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in node.find_all("p")]
        paragraphs = [p for p in paragraphs if len(p) >= 30 and normalized_title(p) != normalized_title(title) and not re.search(
            r"무단.{0,10}전재|저작권|구독 신청|로그인|댓글|@", p
        )]
        if paragraphs:
            bodies.append(" ".join(paragraphs[:3]))
        elif len(node.get_text(" ", strip=True)) >= 40:
            bodies.append(node.get_text(" ", strip=True))
    for body in bodies:
        text = clean_text(body)
        if len(text) >= 40:
            return brief(text, limit), "본문 발췌"
    # The publisher's own article description is acceptable, but label its origin explicitly.
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        meta = soup.find("meta", attrs=attrs)
        text = clean_text(meta.get("content", "")) if meta else ""
        if len(text) >= 40 and normalized_title(text) != normalized_title(title):
            return brief(text, limit), "출처 요약문"
    return "", "본문 식별 불가"


class SourceRedirects(HTTPRedirectHandler):
    def __init__(self, source_url: str):
        super().__init__()
        self.source_url = source_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_https(newurl, self.source_url):
            raise ValueError("원문 출처 범위 밖 리디렉션")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def summarize_card(card: Card, url: str) -> Card:
    if not public_https(url, card.article.source_url or card.article.url):
        return replace(card, summary="", summary_kind="확인 불가", summary_url="", summary_detail="원문 URL/출처 확인 불가")
    try:
        opener = build_opener(SourceRedirects(card.article.source_url or card.article.url))
        with opener.open(Request(url, headers={"User-Agent": "PublicFinanceCardletter/0.2"}), timeout=15) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("본문 크기 제한 초과")
        summary, kind = extract_summary(data, card.article.title, limit=480)
        if not summary:
            return replace(card, summary="", summary_kind="확인 불가", summary_url=url, summary_detail=kind)
        return replace(card, summary=summary, summary_kind=kind, summary_url=url, summary_detail="")
    except Exception as exc:
        detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
        return replace(card, summary="", summary_kind="확인 불가", summary_url=url, summary_detail=detail)


def enrich(cards: list[Card]) -> list[Card]:
    google = [c for c in cards if urlsplit(c.article.url).hostname == "news.google.com"]
    decoded = {}
    if google:
        try:
            results = asyncio.run(gnews_decoder_async([c.article.url for c in google], timeout=10, concurrency=4))
            decoded = {card.article.url: result.get("decoded_url", "")
                       for card, result in zip(google, results) if result.get("success")}
        except Exception:
            # Resolution failures remain explicit; no invented summary or access-control bypass.
            decoded = {}
    def work(card):
        url = decoded.get(card.article.url, "") if card in google else card.article.url
        if not url:
            return replace(card, summary="", summary_kind="확인 불가", summary_url="", summary_detail="원문 링크 해석 실패")
        return summarize_card(card, url)
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(work, cards))
