from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from .news import Card, Coverage
from .rankings import Roster

ROOT = Path(__file__).resolve().parents[1]
NAVY = colors.HexColor("#122C47")
INK = colors.HexColor("#182D40")
TEAL = colors.HexColor("#007F7B")
GRAY = colors.HexColor("#54687A")


def setup_fonts() -> None:
    for name, filename in (("KR", "NanumGothic-Regular.ttf"), ("KR-Bold", "NanumGothic-Bold.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(ROOT / "assets" / "fonts" / filename)))


def paragraph(c: canvas.Canvas, text: str, x: float, top: float, width: float,
              size: float = 9, color=INK, bold: bool = False, max_height: float = 100) -> float:
    style = ParagraphStyle("text", fontName="KR-Bold" if bold else "KR", fontSize=size,
                           leading=size * 1.45, textColor=color, wordWrap="CJK")
    p = Paragraph(text, style)
    _, height = p.wrap(width, max_height)
    if height > max_height + 0.01:
        raise ValueError("카드 텍스트가 A4 레이아웃 한도를 초과했습니다")
    p.drawOn(c, x, top - height)
    return top - height


def shortened(text: str, count: int) -> str:
    return text if len(text) <= count else text[:count - 1] + "…"


def render(path: Path, cards: list[Card], coverage: list[Coverage], as_of: datetime,
           hours: int, demo: bool = False, roster: Roster | None = None) -> None:
    if len(cards) > 6:
        raise ValueError("최대 6개 카드만 지원합니다")
    setup_fonts()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    weekday = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")[as_of.weekday()]
    title = f"{as_of:%Y/%m/%d}/{weekday} Daily News"
    c.setTitle(title + (" · 디자인 샘플" if demo else ""))
    c.setAuthor("Public Finance Cardletter")
    width, height = A4
    margin = 32
    content_width = width - 2 * margin
    c.setFillColor(colors.HexColor("#F4F7FA"))
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, height - 106, width, 106, fill=1, stroke=0)
    paragraph(c, "PUBLIC FINANCE / MORNING BRIEF", margin, height - 17,
              content_width, 8, colors.HexColor("#85D8D0"), bold=True)
    paragraph(c, title, margin, height - 36, content_width, 19, colors.white, True)
    paragraph(c, "부동산 PF · 캐피탈 · 개인/리테일 · TOP100 시공사", margin, height - 70,
              content_width, 10, colors.white)
    paragraph(c, f"{as_of:%Y.%m.%d}  |  {as_of:%H:%M} KST 기준  |  최근 {hours}시간  |  {len(cards)}건",
              margin, height - 90, content_width, 7.5, colors.HexColor("#BED0DE"))

    missing_summaries = sum(not card.summary for card in cards)
    if demo:
        notice = "디자인 샘플 · 기사·시공사명·순위·요약은 모두 가상 예시입니다."
        notice_color = colors.HexColor("#A5480B")
    elif not any(item.ok for item in coverage):
        notice = "수집 실패 · 최신 소식 확인 불가. 뉴스 수집 상태를 확인하세요."
        notice_color = colors.HexColor("#B43832")
    else:
        notes = []
        if any(not item.ok for item in coverage):
            notes.append("일부 수집 미완료")
        if missing_summaries:
            notes.append(f"원문 미확인 {missing_summaries}건은 요약 보류")
        notice = " · ".join(notes) if notes else "공개 원문 기반 간략 요약 · 상세 내용은 원문에서 확인하세요."
        notice_color = colors.HexColor("#A5480B") if notes else TEAL
    paragraph(c, notice, margin, height - 122, content_width, 8, notice_color, max_height=26)

    def draw_card(card: Card, top: float) -> float:
        card_height = 78
        c.setFillColor(colors.white)
        c.roundRect(margin, top - card_height, content_width, card_height, 8, fill=1, stroke=0)
        x, inner_width = margin + 14, content_width - 28
        bottom = paragraph(c, escape(shortened(card.article.title, 80)), x, top - 7,
                           inner_width, 9.5, INK, True, max_height=28)
        if card.summary:
            summary = "요약  " + escape(shortened(card.summary, 105))
            summary_color = GRAY
        else:
            summary = "요약 보류  원문을 확인하지 못해 뉴스 내용을 요약하지 않았습니다."
            summary_color = colors.HexColor("#9D632C")
        paragraph(c, summary, x, bottom - 3, inner_width, 8, summary_color, max_height=24)
        timestamp = card.article.published.astimezone(as_of.tzinfo).strftime(
            "%m.%d (시각 미제공)" if card.article.date_only else "%m.%d %H:%M KST"
        )
        rank_tag = "시평 " + ",".join(str(r) for r in card.contractor_ranks) + "위 · " if card.contractor_ranks else ""
        meta = rank_tag + shortened(card.article.publisher, 20) + " · " + timestamp
        paragraph(c, escape(meta), x, top - 64, inner_width, 6.8, GRAY, max_height=11)
        if not demo:
            c.linkURL(card.summary_url or card.article.url,
                      (margin, top - card_height, width - margin, top), relative=0)
        return top - card_height - 4

    def draw_empty(top: float, slots: int, message: str) -> float:
        box_height = slots * 82 - 4
        c.setFillColor(colors.HexColor("#EAF0F4"))
        c.roundRect(margin, top - box_height, content_width, box_height, 8, fill=1, stroke=0)
        paragraph(c, escape(message), margin + 14, top - 18, content_width - 28, 9, GRAY, max_height=40)
        return top - slots * 82

    main = [card for card in cards if card.category not in ("캐피탈업권", "TOP100 시공사", "개인·리테일 금융")]
    capital = [card for card in cards if card.category == "캐피탈업권"]
    retail = [card for card in cards if card.category == "개인·리테일 금융"]
    contractors = [card for card in cards if card.category == "TOP100 시공사"]
    if len(main) > 2 or len(capital) > 1 or len(contractors) > 2 or len(retail) > 1:
        raise ValueError("칸별 카드 한도는 PF·정책 2 / 캐피탈 1 / 개인·리테일 1 / 시공사 2입니다")
    top = height - 156
    sections = (
        ("01  부동산 PF · 정책", main, 2, "조회 기간에 조건을 충족한 PF·정책 소식이 없습니다."),
        ("02  캐피탈업권", capital, 1, "조회 기간에 조건을 충족한 캐피탈사 금융 소식이 없습니다."),
        ("03  개인·리테일 금융", retail, 1, "조회 기간에 조건을 충족한 개인·리테일 금융 소식이 없습니다."),
        ("04  TOP100 시공사 주요 뉴스", contractors, 2,
         "공식 TOP100 명단 확인 대기 · 대상 시공사의 순위와 소속을 아직 검증하지 못했습니다."
         if not roster else "조회 기간에 해당 TOP100 시공사 주요 뉴스가 선정되지 않았습니다."),
    )
    for label, section_cards, slots, empty_message in sections:
        paragraph(c, label, margin, top, content_width, 9, TEAL, True, max_height=14)
        top -= 18
        for card in section_cards:
            top = draw_card(card, top)
        if len(section_cards) < slots:
            top = draw_empty(top, slots - len(section_cards), empty_message)
        top -= 8

    status = " / ".join(f"{x.name} " + ("샘플" if demo else f"{x.count}건" if x.ok else "미완료") for x in coverage)
    paragraph(c, "수집 상태  " + escape(status), margin, 89, content_width, 6.5, GRAY, max_height=22)
    ranking_label = (
        "시평 기준: 가상 샘플 명단 (실제 순위 아님)" if demo else
        f"시평 기준: {roster.year}년 토목건축공사업 TOP100 · 공식 자료 대조 명단" if roster else
        "시평 기준: 공식 명단 미확정 · TOP100 소속을 추정하지 않습니다."
    )
    paragraph(c, ranking_label, margin, 59, content_width, 6.8, GRAY, max_height=11)
    if roster and not demo:
        c.linkURL(roster.source_url, (margin, 46, width - margin, 60), relative=0)
    paragraph(c, "요약: 원문 발췌 또는 언론사 설명문 · 원문 미확인 시 요약 보류 · 내부 개인정보 미사용",
              margin, 40, content_width, 6.5, GRAY, max_height=11)
    paragraph(c, "공식기관 최신 게시판·공개 RSS 검색 기준으로 누락 가능 · 날짜만 제공된 공지는 기간 내 날짜 기준",
              margin, 26, content_width, 6.5, GRAY, max_height=11)
    c.showPage()
    c.save()
