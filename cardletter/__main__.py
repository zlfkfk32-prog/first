from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .news import Article, Coverage, SOURCE_NAMES, collect, select, to_record
from .pdf import render
from .html import render as render_html
from .rankings import DEFAULT_PATH, demo_roster, load_roster
from .summaries import enrich


KST = ZoneInfo("Asia/Seoul")


def demo_articles(as_of: datetime) -> list[Article]:
    items = [
        ("[가상 예시] 부동산 PF 사업성 평가 기준 점검", "가상 금융기관", "금융위원회", True),
        ("[가상 예시] 부동산 금융 조달 여건 변화", "가상 경제매체", "부동산 PF·금융", False),
        ("[가상 예시] NH농협캐피탈 대출 건전성 관리 강화", "가상 금융매체", "캐피탈업권", False),
        ("[가상 예시] 자동차금융 할부 조건과 금융소비자 보호 점검", "가상 금융매체", "개인·리테일 금융", False),
        ("[가상 예시] 샘플건설001 신규 정비사업 수주", "가상 건설매체", "TOP100 시공사", False),
        ("[가상 예시] 샘플건설057 PF 관련 유동성 점검", "가상 건설매체", "TOP100 시공사", False),
        ("[가상 예시] 금융권 인수금융 심사 체계 점검", "가상 금융매체", "기업금융·IB", False),
        ("[가상 예시] 신기술금융 펀드 투자 전략 점검", "가상 투자매체", "투자", False),
        ("[가상 예시] 금융권 연체율과 충당금 관리 기준 점검", "가상 금융매체", "리스크관리", False),
        ("[가상 예시] 금융권 보안 점검과 정보유출 대응 체계 검토", "가상 IT매체", "IT·디지털", False),
    ]
    return [Article(t, f"https://example.com/sample/{i}", p, as_of - timedelta(hours=i + 1), f, o)
            for i, (t, p, f, o) in enumerate(items)]


def main() -> int:
    parser = argparse.ArgumentParser(description="공개정보 A4 한 장 카드레터. 메일 발송 기능은 없습니다.")
    parser.add_argument("--demo", action="store_true", help="가상 기사로 디자인 샘플 생성; 네트워크 미사용")
    parser.add_argument("--hours", type=int, default=24, help="뉴스 조회 기간(기본 24시간)")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--rankings", type=Path, default=DEFAULT_PATH, help="공식 TOP100 대조 명단 JSON")
    args = parser.parse_args()
    if not 1 <= args.hours <= 168:
        parser.error("--hours는 1~168 사이여야 합니다")
    as_of = datetime.now(KST)
    ranking_issue = ""
    if args.demo:
        roster = demo_roster(as_of.year)
        articles = demo_articles(as_of)
        coverage = [Coverage(name, True, 0, "가상 데이터; 네트워크 수집 미실행") for name in SOURCE_NAMES]
    else:
        try:
            roster = load_roster(args.rankings)
            if roster.year > as_of.year:
                raise ValueError("미래 연도 시공능력평가 명단")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            roster = None
            ranking_issue = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        articles, coverage = collect(args.hours, roster)
    cards = select(articles, as_of, args.hours, roster=roster)
    detail_cards = select(articles, as_of, args.hours, limit=32, roster=roster, detailed=True)
    if args.demo:
        sample_briefs = (
            "[가상 요약] PF 사업장 평가 기준을 점검하는 내용입니다. 금융당국의 적용 대상과 시행 일정 확인을 가정한 예시입니다.",
            "[가상 요약] 부동산 금융의 조달 조건이 변화했다는 예시입니다. 실제 금리·조건을 나타내지 않습니다.",
            "[가상 요약] 캐피탈사가 대출 건전성 관리 방침을 강화했다는 예시입니다. 실제 회사의 발표가 아닙니다.",
            "[가상 요약] 자동차 할부 조건과 소비자 보호 기준을 점검하는 예시입니다. 실제 금융상품 조건이 아닙니다.",
            "[가상 요약] 가상 시공사가 정비사업 수주를 발표했습니다. 수주 규모와 사업 일정 확인을 가정한 예시입니다.",
            "[가상 요약] 가상 시공사의 PF 유동성 점검 소식입니다. 실제 시공사의 신용·재무 상태를 나타내지 않습니다.",
        )
        sample_briefs += (
            "[가상 요약] 인수 대상 기업의 현금흐름과 거래 구조를 확인하는 심사 절차를 점검한다는 예시입니다. 실제 거래나 규제 변경을 뜻하지 않습니다.",
            "[가상 요약] 신기술금융 펀드의 투자 대상과 회수 계획을 검토하는 예시입니다. 실제 투자 성과나 조건을 나타내지 않습니다.",
            "[가상 요약] 연체율 집계 기준과 충당금 적립 조건을 확인하는 예시입니다. 실제 업권 수치나 회사 손실을 나타내지 않습니다.",
            "[가상 요약] 외부 연결 시스템의 접근권한과 정보유출 대응 절차를 점검하는 예시입니다. 실제 사고 발생을 뜻하지 않습니다.",
        )
        detail_cards = [replace(card, summary=sample_briefs[demo_articles(as_of).index(card.article)], summary_kind="가상 예시") for card in detail_cards]
        cards = [replace(card, summary=sample_briefs[demo_articles(as_of).index(card.article)], summary_kind="가상 예시") for card in cards]
    else:
        combined = {card.article.url: card for card in detail_cards + cards}
        enriched = {card.article.url: card for card in enrich(list(combined.values()))}
        cards = [enriched[c.article.url] for c in cards]
        detail_cards = [enriched[c.article.url] for c in detail_cards]
    suffix = "-sample" if args.demo else ""
    stem = f"cardletter-{as_of:%Y-%m-%d}{suffix}"
    args.output.mkdir(parents=True, exist_ok=True)
    render(args.output / (stem + ".pdf"), cards, coverage, as_of, args.hours, args.demo, roster)
    render_html(args.output / (stem + ".html"), detail_cards, coverage, as_of, args.demo)
    record = {
        "as_of": as_of.isoformat(), "demo": args.demo, "lookback_hours": args.hours,
        "coverage": [asdict(c) for c in coverage], "cards": [to_record(c) for c in cards],
        "contractor_ranking": {"year": roster.year, "source_url": roster.source_url,
                               "source_sha256": roster.source_sha256, "demo": roster.demo} if roster else None,
        "ranking_issue": ranking_issue,
        "detail_cards": [to_record(c) for c in (detail_cards)],
    }
    (args.output / (stem + ".json")).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in coverage:
        status = "SAMPLE" if args.demo else "OK" if item.ok else "FAILED"
        print(f"{item.name}: {status} ({item.count}) {item.detail}")
    print(f"PDF: {args.output / (stem + '.pdf')}")
    print(f"HTML: {args.output / (stem + '.html')}")
    print(f"Summaries: {sum(bool(c.summary) for c in cards)}/{len(cards)}")
    if ranking_issue:
        print(f"TOP100: {ranking_issue}")
    if not any(item.ok for item in coverage):
        print("ERROR: 모든 수집이 실패했습니다. PDF는 수집 실패 안내이며 뉴스레터가 아닙니다.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
