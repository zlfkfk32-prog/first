from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .news import Article, Coverage, to_record
from .naver import collect, verify
from .estate import prepare, balanced, digest, GROUPS
from dotenv import load_dotenv
from .pdf import render
from .html import render as render_html
from .rankings import DEFAULT_PATH, demo_roster, load_roster
from .mail import send_briefing, check_settings


KST = ZoneInfo("Asia/Seoul")


def demo_articles(as_of: datetime) -> list[Article]:
    items = [
        ("[가상 예시] 부동산 PF 사업성 평가 기준 점검", "가상 금융기관", "금융위원회", True),
        ("[가상 예시] 부동산 금융 조달 여건 변화", "가상 경제매체", "부동산 PF·금융", False),
        ("[가상 예시] NH농협캐피탈 부동산 사업장 담보대출 조달 조건 점검", "가상 금융매체", "캐피탈업권", False),
        ("[가상 예시] 서울 아파트 입주 일정과 전세대출 금융소비자 보호 점검", "가상 금융매체", "개인·리테일 금융", False),
        ("[가상 예시] 샘플건설001 신규 정비사업 수주", "가상 건설매체", "TOP100 시공사", False),
        ("[가상 예시] 샘플건설057 부산 공사현장 하자 발생 관련 점검", "가상 건설매체", "TOP100 시공사", False),
        ("[가상 예시] 물류센터 사업장 인수금융 구조와 매각 절차 점검", "가상 금융매체", "기업금융·IB", False),
        ("[가상 예시] 신기술금융 펀드 산업단지 개발 투자 전략 점검", "가상 투자매체", "투자", False),
        ("[가상 예시] 금융권 건설사업장 연체율과 충당금·보증 관리 점검", "가상 금융매체", "리스크관리", False),
        ("[가상 예시] 금융권 연계 공사현장 디지털 안전기술 도입 검토", "가상 IT매체", "IT·디지털", False),
    ]
    return [Article(t, f"https://example.com/sample/{i}", p, as_of - timedelta(hours=i + 1), f, o)
            for i, (t, p, f, o) in enumerate(items)]


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    parser = argparse.ArgumentParser(description="NAVER 뉴스 API 기반 부동산 데일리 뉴스레터")
    parser.add_argument("--demo", action="store_true", help="가상 기사로 확인; 네트워크·발송 미사용")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--rankings", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--check-config", action="store_true", help="키/메일 설정 유무만 점검; 값 표시·API 호출·발송 없음")
    parser.add_argument("--send-email", action="store_true", help="Microsoft Graph로 실제 메일 발송; 회사 권한과 설정 필요")
    args = parser.parse_args()
    if not 1 <= args.hours <= 168: parser.error("--hours는 1~168 사이여야 합니다")
    if args.demo and args.send_email: parser.error("가상 샘플은 메일로 발송할 수 없습니다")
    if args.check_config:
        import os
        for name in ('NAVER_CLIENT_ID', 'NAVER_CLIENT_SECRET'):
            print(name + ': ' + ('설정됨' if os.getenv(name) else '설정 필요'))
        check_settings()
        return 0
    as_of = datetime.now(KST)
    ranking_issue = ""
    if args.demo:
        roster = demo_roster(as_of.year)
        titles = (
            '[가상 예시] 샘플건설057 부산 공사현장 하자 발생 점검',
            '[가상 예시] 서울 정비사업 착공 일정 점검',
            '[가상 예시] 대전 산업단지 공사현장 준공 일정 점검',
            '[가상 예시] 경기 평택 부동산 PF 본PF 전환 점검',
            '[가상 예시] 부산 물류센터 PF 브리지론 만기 점검',
            '[가상 예시] 샘플건설001 신규 정비사업 수주',
            '[가상 예시] 전국 부동산 PF 대주단 협의 점검',
            '[가상 예시] 광주 아파트 미분양 동향 점검',
        )
        articles = [Article(t, f'https://example.com/sample/{i}', '가상 뉴스매체', as_of-timedelta(hours=i+1), '가상 NAVER 결과') for i,t in enumerate(titles)]
        coverage = [Coverage('NAVER 뉴스 API', True, 0, '가상 데이터 · 실제 API/원문 접속 미실행', '가상')]
        verified = [replace(c, summary='[가상 요약] ' + c.article.title.removeprefix('[가상 예시] ') + '을 가정한 디자인 예시입니다. 실제 사업장·사건·수치가 아닙니다.', summary_kind='가상 예시') for c in prepare(articles, as_of, args.hours, roster)]
        api_ok = True
    else:
        try:
            roster = load_roster(args.rankings)
            if roster.year > as_of.year: raise ValueError('미래 연도 명단')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            roster = None
            ranking_issue = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        articles, coverage = collect(args.hours, roster)
        api_ok = any(c.ok for c in coverage)
        # Bounded preselection with section diversity; verify before final selection.
        candidates = balanced(prepare(articles, as_of, args.hours, roster), limit=80, per_group=20)
        verified, validation = verify(candidates)
        if not api_ok:
            validation = replace(validation, ok=False, detail='NAVER 수집 실패로 원문 검사 미실행')
        coverage.append(validation)
    detail_cards = balanced(verified)
    cards = digest(detail_cards)
    suffix = '-sample' if args.demo else ''
    stem = f'cardletter-{as_of:%Y-%m-%d}{suffix}'
    args.output.mkdir(parents=True, exist_ok=True)
    pdf_path = args.output / (stem + '.pdf')
    html_path = args.output / (stem + '.html')
    render(pdf_path, cards, coverage, as_of, args.hours, args.demo, roster, estate=True)
    render_html(html_path, detail_cards, coverage, as_of, args.demo)
    record = {
        'as_of': as_of.isoformat(), 'demo': args.demo, 'lookback_hours': args.hours,
        'source': 'NAVER News Search API', 'coverage': [asdict(c) for c in coverage],
        'cards': [to_record(c) for c in cards], 'detail_cards': [to_record(c) for c in detail_cards],
        'contractor_ranking': {'year': roster.year, 'source_url': roster.source_url, 'source_sha256': roster.source_sha256, 'demo': roster.demo} if roster else None,
        'ranking_issue': ranking_issue,
    }
    (args.output / (stem + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    for c in coverage: print(c.name + ': ' + ('OK' if c.ok else 'FAILED') + f' ({c.count}) ' + c.detail)
    print('PDF: ' + str(pdf_path))
    print('HTML: ' + str(html_path))
    if not api_ok:
        print('ERROR: NAVER API 수집 실패. 설정/권한/네트워크를 확인하세요. 발송하지 않습니다.')
        return 2
    if args.send_email:
        if not detail_cards:
            print('ERROR: 원문 검증을 통과한 기사가 없어 발송하지 않습니다.')
            return 2
        try:
            result = send_briefing(pdf_path, html_path, detail_cards, as_of, args.output / '.mail-state')
            print('MAIL: ' + result)
        except Exception as exc:
            # Credential values and API response bodies are never logged.
            print('MAIL ERROR: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
            return 3
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
