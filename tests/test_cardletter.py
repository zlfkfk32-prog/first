from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from cardletter.__main__ import demo_articles, main
from cardletter.news import Article, Card, Coverage, Feed, OFFICIAL_BOARDS, collect, is_capital_news, parse_feed, parse_official, select
from cardletter.pdf import render
from cardletter.rankings import Contractor, Roster, demo_roster, load_roster
from cardletter.summaries import brief, enrich, extract_summary, public_https, summarize_card

NOW = datetime(2026, 10, 11, 8, tzinfo=ZoneInfo("Asia/Seoul"))
ROSTER = demo_roster(2026)


def sample_cards():
    return [replace(c, summary="가상 뉴스 요약입니다. 실제 사실 확인 자료가 아닙니다.", summary_kind="가상 예시")
            for c in select(demo_articles(NOW), NOW, 24, roster=ROSTER)]


class NewsTests(unittest.TestCase):
    def article(self, title, hours=1, url="https://example.com/1", official=False):
        return Article(title, url, "공개 테스트 출처", NOW - timedelta(hours=hours), "테스트", official)

    def test_freshness_and_irrelevant_filter(self):
        articles = [self.article("부동산 PF 최신 보도"), self.article("부동산 PF 오래된 보도", 25),
                    self.article("부동산 PF 미래 보도", -1), self.article("오늘의 스포츠")]
        self.assertEqual([c.article.title for c in select(articles, NOW, 24)], ["부동산 PF 최신 보도"])

    def test_duplicates_removed_across_sources(self):
        a = self.article("부동산 PF 사업성 점검")
        b = self.article("부동산 PF 사업성 점검!", url="https://example.com/2")
        self.assertEqual(len(select([a, b], NOW, 24)), 1)

    def test_fixed_sections_and_official_priority(self):
        articles = demo_articles(NOW) + [self.article("부동산 주택 공급"), self.article("NH농협캐피탈 대출 실적", url="https://example.com/more")]
        cards = select(articles, NOW, 24, roster=ROSTER)
        self.assertEqual(len(cards), 6)
        self.assertEqual(sum(c.category == "캐피탈업권" for c in cards), 1)
        self.assertEqual(sum(c.category == "TOP100 시공사" for c in cards), 2)
        self.assertEqual(sum(c.category == "개인·리테일 금융" for c in cards), 1)
        self.assertTrue(any(c.article.official for c in cards))
        self.assertEqual({rank for c in cards for rank in c.contractor_ranks}, {1, 57})

    def test_retail_separate_from_capital_and_pf(self):
        for title in ("현대캐피탈 자동차금융 할부 조건 변경", "가계대출 금융소비자 보호 강화", "주택담보대출 금리 변화"):
            self.assertEqual(select([self.article(title)], NOW, 24)[0].category, "개인·리테일 금융")
        self.assertEqual(select([self.article("부동산 PF 대출 심사 강화")], NOW, 24)[0].category, "부동산 PF")

    def test_unranked_contractor_not_labeled_top100(self):
        articles = [self.article("명단밖건설 신규 수주"), self.article("샘플건설001 정비사업 수주", url="https://example.com/2")]
        cards = select(articles, NOW, 24, roster=ROSTER)
        self.assertEqual([c.article.title for c in cards if c.category == "TOP100 시공사"], ["샘플건설001 정비사업 수주"])
        self.assertFalse(any(c.category == "TOP100 시공사" for c in select(articles, NOW, 24)))

    def test_capital_company_business_not_sports_foreign_vc_or_banks(self):
        self.assertTrue(is_capital_news("NH농협캐피탈 대표 연임과 실적 점검"))
        self.assertTrue(is_capital_news("장종환 NH농협캐피탈 대표 연임 앞에 놓인 변수들, 하반기 실적에 지주 지배구조 변화도 관건"))
        self.assertTrue(is_capital_news("NH농협캐피탈, AX 중장기 로드맵 1.0 수립 및 현장 이사회"))
        self.assertTrue(is_capital_news("캐피탈사 회사채 조달 여건 개선"))
        for title in ["현대캐피탈 배구단 우승", "허수봉 현대캐피탈 연봉", "캐피탈 원 주식 매도",
                      "벤처캐피탈 투자 증가", "NH농협은행 기업금융 확대", "캐피탈 토토 이벤트"]:
            self.assertFalse(is_capital_news(title), title)
            self.assertFalse(select([self.article(title)], NOW, 24), title)

    def test_rss_official_provenance_requires_matching_domain(self):
        rss = b'''<rss><channel><item><title>PF review - Agency</title>
        <link>https://news.google.com/rss/articles/a</link>
        <pubDate>Sat, 10 Oct 2026 23:00:00 GMT</pubDate>
        <source url="https://www.fsc.go.kr">Agency</source></item></channel></rss>'''
        feed = Feed("금융위원회", "site:fsc.go.kr", "fsc.go.kr")
        parsed = parse_feed(rss, feed)
        self.assertEqual(parsed[0].title, "PF review")
        self.assertEqual(parsed[0].source_url, "https://www.fsc.go.kr")
        self.assertTrue(parsed[0].official)
        self.assertEqual(parse_feed(rss.replace(b"www.fsc.go.kr", b"fsc.go.kr.evil.test"), feed), [])

    def test_invalid_dates_and_unsafe_links_skipped(self):
        rss = b'''<rss><channel><item><title>test</title><link>javascript:alert(1)</link>
        <pubDate>Sat, 10 Oct 2026 23:00:00 GMT</pubDate></item>
        <item><title>test</title><link>https://example.com</link><pubDate>bad date</pubDate></item></channel></rss>'''
        self.assertEqual(parse_feed(rss, Feed("test", "test")), [])

    def test_html_is_not_successful_empty_feed(self):
        with self.assertRaises(ValueError):
            parse_feed(b"<html><body>Access denied</body></html>", Feed("test", "test"))

    def test_official_board_dates_links_and_schema_failure(self):
        fsc = '''<li><a href="/no010101/87900?curPage=1&amp;srchText=">부동산 PF 기준</a>
                 <div class="day">2026-10-10</div></li>'''.encode()
        fss = '''<tr><td class="title"><a href="/fss/bbs/B0000188/view.do?nttId=238317&amp;menuNo=200218">
                 캐피탈 대출 점검</a></td><td>2026-10-10</td></tr>'''.encode()
        for data, board in zip((fsc, fss), OFFICIAL_BOARDS):
            item = parse_official(data, board)[0]
            self.assertTrue(item.official)
            self.assertTrue(item.date_only)
            self.assertNotIn("&amp;", item.url)
            self.assertEqual(len(select([item], NOW, 24)), 1)
        with self.assertRaises(ValueError):
            parse_official(b"<html>server challenge</html>", OFFICIAL_BOARDS[0])


class RosterTests(unittest.TestCase):
    def fixture(self, folder):
        data = {"verified": True, "category": "토목건축공사업", "year": 2026,
                "source_url": "https://www.cak.or.kr/public-test-fixture", "source_file": "source.txt",
                "source_sha256": hashlib.sha256(b"public-source-fixture").hexdigest(),
                "contractors": [{"rank": i, "name": f"테스트건설{i:03d}", "aliases": []} for i in range(1, 101)]}
        p = Path(folder)
        (p / "source.txt").write_bytes(b"public-source-fixture")
        (p / "rankings.json").write_text(json.dumps(data), encoding="utf-8")
        return p / "rankings.json", data

    def test_complete_roster_queries_cover_all_100(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.fixture(folder)
            roster = load_roster(path)
            self.assertEqual(len(roster.contractors), 100)
            joined = " ".join(roster.queries())
            self.assertIn('"테스트건설001"', joined)
            self.assertIn('"테스트건설100"', joined)
            self.assertEqual(len(roster.matches("테스트건설100, PF 유동성 점검")), 1)

    def test_partial_or_unverified_roster_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as folder:
            path, data = self.fixture(folder)
            for mutation in ({"verified": False}, {"contractors": data["contractors"][:99]},
                             {"source_sha256": "wrong"}, {"category": "소방시설공사업"}):
                path.write_text(json.dumps({**data, **mutation}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_roster(path)

    def test_ambiguous_company_names_and_aliases(self):
        roster = Roster(2026, "https://www.cak.or.kr", "", (Contractor(1, "한양"), Contractor(2, "DL이앤씨", ("디엘이앤씨",))))
        self.assertFalse(roster.matches("한양대학교 건축학과 소식"))
        self.assertEqual(roster.matches("한양은 신규 수주를 발표했다")[0].name, "한양")
        self.assertEqual(roster.matches("디엘이앤씨, PF 사업 점검")[0].rank, 2)

    def test_demo_roster_never_used_for_live_collection(self):
        with self.assertRaises(ValueError):
            collect(24, ROSTER)


class SummaryTests(unittest.TestCase):
    def test_extracts_public_body_not_navigation_or_ads(self):
        data = '''<html><nav>은행 광고</nav><article><aside>광고</aside>
        <p>NH농협캐피탈은 대출 건전성 관리 방안을 발표했다. 연체 관리와 조달 구조 점검을 추진한다고 밝혔다.</p>
        <p class="copyright">무단 전재 금지</p></article></html>'''.encode()
        text, kind = extract_summary(data, "NH농협캐피탈 건전성 관리 강화")
        self.assertIn("대출 건전성", text)
        self.assertNotIn("광고", text)
        self.assertEqual(kind, "본문 발췌")
        self.assertLessEqual(len(text), 112)

    def test_jsonld_and_publisher_description_are_labeled(self):
        body = "시공사는 정비사업 수주 계획을 발표했다. 사업 추진 일정과 금융 조달 방안을 검토한다고 설명했다."
        data = ('<script type="application/ld+json">' + json.dumps({"@type": "NewsArticle", "articleBody": body}) + '</script>').encode()
        self.assertEqual(extract_summary(data, "정비사업 수주")[1], "본문 발췌")
        data = f'<meta property="og:description" content="{body}">'.encode()
        self.assertEqual(extract_summary(data, "정비사업 수주")[1], "출처 요약문")

    def test_businesspost_br_body_and_photo_caption(self):
        data = '''<div id="article-body-content">[비즈니스포스트] NH농협캐피탈 대표의 연임에는 실적과 지배구조 변수가 있다.<br>
        <figure><figcaption>이 내용은 사진 설명이라 요약에서 제외해야 한다.</figcaption></figure>
        하반기 경영 성과가 평가의 주요 변수가 될 전망이다.</div>'''.encode()
        summary, kind = extract_summary(data, "NH농협캐피탈 대표 연임 변수")
        self.assertIn("실적과 지배구조", summary)
        self.assertNotIn("사진 설명", summary)
        self.assertEqual(kind, "본문 발췌")

    def test_mismatched_or_gated_page_not_summarized(self):
        self.assertFalse(extract_summary(b"<html><h1>Access Denied</h1></html>", "PF 뉴스")[0])
        data = '<meta property="og:title" content="홈페이지"><article><p>아무 관련 없는 광고가 긴 문장으로 표시됩니다. 접속 페이지가 실제 기사가 아닙니다.</p></article>'.encode()
        self.assertFalse(extract_summary(data, "부동산 PF 사업성 점검 발표")[0])

    def test_no_body_no_invented_title_summary(self):
        self.assertFalse(extract_summary('<h1>캐피탈 대출 실적</h1>'.encode(), "캐피탈 대출 실적")[0])
        card = sample_cards()[0]
        with patch("cardletter.summaries.build_opener") as opener:
            opener.return_value.open.side_effect = OSError("network blocked")
            result = summarize_card(card, "https://example.com/sample/0")
        # Failure must clear any previously attached text, rather than leave a stale summary.
        self.assertEqual(result.summary_kind, "확인 불가")
        self.assertEqual(result.summary, "")
        self.assertEqual(result.summary_detail, "OSError")

    def test_private_mismatched_or_non_https_urls_rejected(self):
        for target in ["http://example.com/a", "https://127.0.0.1/a", "https://example.com.evil.test/a",
                       "https://user:password@example.com/a", "https://example.com:bad/a"]:
            self.assertFalse(public_https(target, "https://example.com"))
        self.assertTrue(public_https("https://www.example.com/a", "https://example.com"))

    def test_empty_enrichment_needs_no_network(self):
        self.assertEqual(enrich([]), [])


class PdfTests(unittest.TestCase):
    def test_sample_one_a4_page_with_four_sections_and_summaries(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "sample.pdf"
            render(target, sample_cards(), [Coverage("가상", True, 5)], NOW, 24, demo=True, roster=ROSTER)
            reader = PdfReader(target)
            self.assertEqual(len(reader.pages), 1)
            page = reader.pages[0]
            self.assertAlmostEqual(float(page.mediabox.width), 595.276, places=2)
            self.assertAlmostEqual(float(page.mediabox.height), 841.89, places=2)
            text = page.extract_text()
            weekday = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")[NOW.weekday()]
            self.assertIn(f"{NOW:%Y/%m/%d}/{weekday} Daily News", text)
            for phrase in ["TOP100 시공사 주요 뉴스", "캐피탈업권", "개인·리테일 금융", "가상 뉴스 요약", "디자인 샘플", "57위"]:
                self.assertIn(phrase, text)
            self.assertFalse(page.get("/Annots"))

    def test_live_links_and_collection_failure_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "report.pdf"
            render(target, sample_cards(), [Coverage("뉴스", True, 5)], NOW, 24)
            page = PdfReader(target).pages[0]
            self.assertEqual(len(page["/Annots"]), 6)
            self.assertNotIn("원문 보기", page.extract_text())
            for annotation, card in zip(page["/Annots"], sample_cards()):
                link = annotation.get_object()
                x1, y1, x2, y2 = map(float, link["/Rect"])
                self.assertAlmostEqual(x1, 32)
                self.assertAlmostEqual(x2, float(page.mediabox.width) - 32, places=2)
                self.assertAlmostEqual(y2 - y1, 78)
                self.assertEqual(link["/A"]["/URI"], card.summary_url or card.article.url)
            render(target, [], [Coverage("뉴스", False, 0, "URLError")], NOW, 24)
            page = PdfReader(target).pages[0]
            self.assertIn("최신 소식 확인 불가", page.extract_text())
            self.assertIn("공식 TOP100 명단 확인 대기", page.extract_text())
            self.assertFalse(page.get("/Annots"))

    def test_maximum_titles_and_summaries_fit_one_page(self):
        with tempfile.TemporaryDirectory() as folder:
            cards = [replace(c, article=replace(c.article, title="부동산 PF <>& " + "긴기사제목" * 40, publisher="출처" * 50),
                             summary="요약문" * 50) for c in sample_cards()]
            target = Path(folder) / "long.pdf"
            render(target, cards, [Coverage("뉴스", True, 5)], NOW, 24, demo=True, roster=ROSTER)
            self.assertEqual(len(PdfReader(target).pages), 1)

    def test_all_sources_fail_returns_failure_and_writes_honest_report(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("sys.argv", ["cardletter", "--output", folder]), patch(
                "cardletter.__main__.collect", return_value=([], [Coverage("뉴스", False, 0, "URLError")])
            ):
                self.assertEqual(main(), 2)
            self.assertIn("수집 실패", PdfReader(next(Path(folder).glob("*.pdf"))).pages[0].extract_text())


if __name__ == "__main__":
    unittest.main()


class DetailedBriefingTests(unittest.TestCase):
    def test_extended_topics_stay_out_of_one_page_slots(self):
        titles = ["금융권 해킹 정보유출 점검", "금융권 인수금융 구조 점검", "신기술금융 펀드 투자 확대", "금융권 연체율 충당금 점검"]
        articles = demo_articles(NOW) + [Article(t, f"https://example.com/extra/{i}", "테스트", NOW, "테스트") for i,t in enumerate(titles)]
        detail = select(articles, NOW, 24, roster=ROSTER, detailed=True, limit=32)
        self.assertTrue({"IT·디지털", "기업금융·IB", "투자", "리스크관리"}.issubset({c.category for c in detail}))
        digest = select(articles, NOW, 24, roster=ROSTER)
        self.assertEqual(len(digest), 6)
        self.assertFalse(any(c.category in {"IT·디지털", "기업금융·IB", "투자", "리스크관리"} for c in digest))

    def test_detail_html_navigation_labels_and_escaping(self):
        from bs4 import BeautifulSoup
        from cardletter.html import render as render_html
        cards = sample_cards()
        cards[0] = replace(cards[0], summary='<script>alert(1)</script> PF 설명', checkpoint='원문 확인 안내')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'brief.html'
            render_html(path, cards, [Coverage('공개', True, 2)], NOW)
            soup = BeautifulSoup(path.read_text(), 'html.parser')
            self.assertIn('무슨 내용인가요?', soup.get_text())
            self.assertIn('일반 검토 안내', soup.get_text())
            self.assertIn('용어 쉽게 보기', soup.get_text())
            self.assertEqual(len(soup.select('#details section')), 8)
            self.assertEqual(len(soup.select('script')), 1)
            for link in soup.select('a[href^="#"]'):
                self.assertIsNotNone(soup.find(id=link['href'][1:]))
            self.assertTrue(soup.select('.news-card a.article-link'))

    def test_longer_extraction_preserves_source_facts(self):
        content = ('금융회사는 자금 조달 조건을 점검하고 대출 건전성과 상환 구조를 관리하며 ' + '관련 계약과 기준일 및 대상 자산을 확인하고 ' * 4 + '심사 체계를 검토한다고 밝혔다. ') * 4
        raw = ('<article><p>' + content + '</p></article>').encode()
        short, _ = extract_summary(raw, '금융회사 자금 조달')
        long, _ = extract_summary(raw, '금융회사 자금 조달', limit=480)
        self.assertGreater(len(long), len(short))
        self.assertIn('상환 구조', long)


class HomeNavigationTests(unittest.TestCase):
    def test_home_is_compact_and_other_pages_start_hidden(self):
        from bs4 import BeautifulSoup
        from cardletter.html import render as render_html
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'brief.html'
            render_html(path, sample_cards(), [], NOW)
            soup = BeautifulSoup(path.read_text(), 'html.parser')
            home = soup.select_one('#home')
            self.assertEqual([h.get_text() for h in home.select('h2')], ['메인 이슈', '부문별로 찾아보기', '오늘의 핵심'])
            self.assertNotIn('업무에서 확인할 점', home.get_text())
            for page in soup.select('.page:not(#home)'):
                self.assertTrue(page.has_attr('hidden'))
            for card in home.select('.news-card'):
                self.assertEqual(card.select_one('.card-foot a').get_text(), '원문 보기 ↗')
                self.assertTrue(card.select_one('.card-foot a')['href'].startswith('https://'))
            self.assertIn('justify-content:center', soup.style.get_text())
            self.assertEqual(len(soup.select('nav a[href^="#section-"]')), 8)


class ProjectFocusTests(unittest.TestCase):
    def article(self, title, index=0, official=False):
        return Article(title, f'https://example.com/project/{index}', '공개 출처', NOW, '공사현장', official)

    def test_major_contractor_issue_leads_before_routine_pf(self):
        items = [self.article('서울 부동산 PF 사업성 점검', 0, True), self.article('샘플건설057 부산 현장 하자 발생', 1), self.article('샘플건설001 서울 정비사업 수주', 2)]
        cards = select(items, NOW, 24, roster=ROSTER, detailed=True, project=True)
        self.assertIn('하자 발생', cards[0].article.title)
        self.assertEqual(cards[0].contractor_ranks, (57,))
        self.assertGreater(cards[0].score, cards[1].score)

    def test_prevention_is_not_reported_as_major_incident(self):
        from cardletter.project_focus import major_issue
        for title in ('건설현장 안전사고 예방 교육', '샘플건설001 무사고 캠페인', '샘플건설001 부도설 부인'):
            self.assertFalse(major_issue(title, ROSTER))
        for title in ('시공사 법정관리 신청', '부산 공사현장 붕괴 사고 발생', '아파트 부실시공 하자 판결'):
            self.assertTrue(major_issue(title, ROSTER))

    def test_project_relevance_and_regional_sites(self):
        unrelated = [self.article('현대캐피탈 자동차 할부금융 확대', 1), self.article('금융권 해킹 사고 발생', 2), self.article('샘플건설001 대표 인사 발표', 3)]
        self.assertFalse(select(unrelated, NOW, 24, roster=ROSTER, detailed=True, project=True))
        regional = [self.article('부산 아파트 공사현장 준공 일정 발표', 4), self.article('대전 산업단지 개발 인허가 발표', 5)]
        self.assertEqual(len(select(regional, NOW, 24, roster=ROSTER, detailed=True, project=True)), 2)
