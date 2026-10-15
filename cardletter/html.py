"""Readable detailed briefing; PDF remains the one-page digest."""
from datetime import datetime
from html import escape
from pathlib import Path
from .news import Card, Coverage

GROUPS = ('부동산 PF·정책', '업권 공통·캐피탈', '기업금융·IB', '개인·리테일 금융', '투자', '리스크관리', 'IT·디지털', 'TOP100 시공사')
DESCRIPTIONS = ('PF·담보·공급·당국 정책', '조달·회사채·캐피탈사 경영', '인수금융·기업대출·구조화·NPL', '가계·개인사업자·자동차금융·소비자 보호', '신기술금융·펀드·지분투자', '연체·충당금·건전성·안전', 'AI·정보보호·전자금융', '공식 시공능력평가 명단 대조')
GLOSSARY = {
    'PF': '개발사업에서 생길 수익을 주요 상환재원으로 삼는 금융입니다.',
    'NPL': '정상적인 원리금 회수가 어려운 부실채권을 뜻합니다.',
    '충당금': '앞으로 발생할 수 있는 손실에 대비해 회계상 미리 반영하는 금액입니다.',
    '연체율': '전체 대출 중 약속한 날짜에 상환되지 않은 대출의 비율입니다. 집계 기준도 확인해야 합니다.',
    '유동성': '필요할 때 현금을 마련해 지급 의무를 이행할 수 있는 정도입니다.',
    '여전채': '캐피탈사·카드사 등 여신전문금융회사가 자금을 조달하기 위해 발행하는 채권입니다.',
    '인수금융': '기업 인수에 필요한 자금을 빌려주거나 조달하는 금융입니다.',
    '리스': '금융회사가 보유한 차량·설비 등을 계약 기간 동안 이용료를 내고 사용하는 방식입니다.',
    '시공능력평가': '공사 실적과 경영·기술능력 등을 종합한 평가입니다. 순위가 신용등급을 뜻하지는 않습니다.',
    '자기자본비율': '관련 자산·위험 등에 비해 자기자본을 얼마나 보유하는지 보는 지표로 제도마다 산식이 다릅니다.',
}


def groups(card: Card) -> tuple[str, ...]:
    primary = {'캐피탈업권': GROUPS[1], '개인·리테일 금융': GROUPS[3], 'TOP100 시공사': GROUPS[7], '기업금융·IB': GROUPS[2], '투자': GROUPS[4], '리스크관리': GROUPS[5], 'IT·디지털': GROUPS[6]}.get(card.category, GROUPS[0])
    result = [primary]
    text = card.article.title.lower()
    for label, words in ((GROUPS[2], ('인수금융', '기업금융', '기업대출', '구조화', 'npl')), (GROUPS[4], ('지분투자', '신기술금융', '펀드')), (GROUPS[5], ('연체', '충당금', '건전성', '유동성', '부실', '신용', '안전')), (GROUPS[6], ('해킹', '정보유출', '정보 유출', '디지털', '보안', '인공지능'))):
        if label not in result and any(word in text for word in words):
            result.append(label)
    return tuple(result)


def article_box(card: Card, as_of: datetime, demo: bool) -> str:
    a = card.article
    title = escape(a.title)
    body = escape(card.summary or '원문을 읽지 못해 요약을 보류했습니다. 제목만으로 내용을 추정하지 않았습니다.')
    label = '가상 예시' if demo else '공식기관 발표' if a.official else '언론 보도'
    stamp = a.published.astimezone(as_of.tzinfo).strftime('%m.%d · 날짜만 제공' if a.date_only else '%m.%d %H:%M KST')
    rank = ' · 시평 ' + ', '.join(map(str, card.contractor_ranks)) + '위' if card.contractor_ranks else ''
    text = a.title + ' ' + card.summary
    terms = ''.join(f'<li><b>{escape(term)}</b> — {escape(definition)}</li>' for term, definition in GLOSSARY.items() if term.lower() in text.lower())
    glossary = f'<details><summary>용어 쉽게 보기</summary><ul>{terms}</ul></details>' if terms else ''
    inner = f'<span class="badge">{label}</span><h3>{title}</h3><div class="meta">{escape(a.publisher)} · {stamp}{rank}</div><h4>무슨 내용인가요?</h4><p>{body}</p><h4>업무에서 확인할 점 <small>일반 검토 안내</small></h4><p>{escape(card.checkpoint)}</p><div class="meta">요약 방식: {escape(card.summary_kind)} · {"본문/설명문 추출 완료 · 사실의 독립 검증을 뜻하지 않음" if card.summary else "추가 원문 확인 필요"}</div>{glossary}'
    if demo:
        content = f'<div>{inner}</div>'
    else:
        content = f'<a class="article-link" href="{escape(card.summary_url or a.url, quote=True)}" target="_blank" rel="noopener noreferrer">{inner.replace(glossary, "")}</a>{glossary}'
    return '<article class="news-card">' + content + '</article>'


def compact_card(card: Card, demo: bool) -> str:
    summary = card.summary or '원문을 확인하지 못해 요약을 보류했습니다.'
    if len(summary) > 150:
        summary = summary[:149].rstrip() + '…'
    content = f'<h3>{escape(card.article.title)}</h3><p>{escape(summary)}</p>'
    if demo:
        link = '<span class="meta">가상 예시 · 원문 없음</span>'
    else:
        link = f'<a href="{escape(card.summary_url or card.article.url, quote=True)}" target="_blank" rel="noopener noreferrer">원문 보기 ↗</a>'
    return f'<article class="news-card compact">{content}<div class="card-foot">{link}</div></article>'


def render(path: Path, cards: list[Card], coverage: list[Coverage], as_of: datetime, demo: bool = False) -> None:
    weekday = ('월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일')[as_of.weekday()]
    title = f'{as_of:%Y/%m/%d}/{weekday} Daily News'
    buckets = {label: [c for c in cards if label in groups(c)] for label in GROUPS}
    tiles = ''.join(f'<a class="tile" href="#section-{i}"><span>{label}</span><b>{len(buckets[label])}건</b><small>{DESCRIPTIONS[i]}</small></a>' for i, label in enumerate(GROUPS))
    sections = []
    for i, label in enumerate(GROUPS):
        items = buckets[label]
        contents = ''.join(article_box(c, as_of, demo) for c in items) or '<p class="empty">선정된 관련 기사가 없습니다. 수집 상태 탭에서 조회 결과를 확인하세요.</p>'
        sections.append(f'<section class="page" id="section-{i}" hidden><h2 tabindex="-1">{label} <small>{len(items)}건</small></h2><p class="meta">{DESCRIPTIONS[i]}</p><div class="grid">{contents}</div></section>')
    lead = compact_card(cards[0], demo) if cards else '<p class="empty">선정 기사 없음 · 수집 상태 탭을 확인하세요.</p>'
    top = ''.join(compact_card(c, demo) for c in cards[:3])
    timeline = ''.join(f'<li><time>{c.article.published.astimezone(as_of.tzinfo):%m.%d}</time> {escape(c.article.title)}</li>' for c in sorted(cards, key=lambda c: c.article.published, reverse=True)[:8])
    states = ''.join(f'<tr><th>{escape(c.name)}</th><td>{"가상 데이터" if demo else "조회 완료" if c.ok else "수집 미완료"}</td><td>{c.count}건</td><td>{escape(c.detail)}</td></tr>' for c in coverage)
    notice = '가상 디자인 샘플 · 기사·회사·순위·요약은 실제 뉴스가 아닙니다.' if demo else '공개 원문 기반 브리핑 · 원문 미확인 기사 요약 보류'
    nav = '<a href="#home">홈</a>' + ''.join(f'<a href="#section-{i}">{label}</a>' for i,label in enumerate(GROUPS)) + '<a href="#sources">수집 상태</a>'
    css = Path(__file__).with_name('briefing.css').read_text(encoding='utf-8')
    script = Path(__file__).with_name('briefing.js').read_text(encoding='utf-8')
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head><body>
<header><h1>{title}</h1><p>{as_of:%H:%M} KST 기준 · {notice}</p></header>
<nav aria-label="부문 메뉴"><div class="nav-inner">{nav}</div></nav>
<main><div class="page" id="home"><section><h2>메인 이슈</h2>{lead}</section><section><h2>부문별로 찾아보기</h2><div class="tiles">{tiles}</div><p class="meta">선정 기사 {len(cards)}건 기준 · 관련 부문 중복 포함 · 전일 대비 수치가 아닙니다.</p></section><section id="highlights"><h2>오늘의 핵심</h2><div class="grid">{top}</div></section></div>
<div id="detail-tools" hidden><label for="search">이 부문에서 회사명·주제 검색</label><input id="search" type="search" placeholder="예: 캐피탈, PF, 자동차, 보안" aria-describedby="search-status"><p id="search-status" class="meta" aria-live="polite"></p></div>
<div id="details">{''.join(sections)}</div>
<section class="page" id="sources" hidden><h2 tabindex="-1">출처와 수집 상태</h2><div class="status"><table><thead><tr><th>출처</th><th>상태</th><th>원시 수집 수</th><th>참고</th></tr></thead><tbody>{states}</tbody></table></div><h2>최근 선정 기사 흐름</h2><p class="meta">기사 게시일 순서이며 같은 사건의 타임라인으로 검증한 내용은 아닙니다.</p><ul>{timeline}</ul><details><summary>금융 용어 사전</summary><ul>{''.join(f'<li><b>{escape(t)}</b> — {escape(d)}</li>' for t,d in GLOSSARY.items())}</ul></details><p class="meta">업무 확인점과 용어 설명은 일반 참고 안내입니다. 출처 표시는 독립적인 사실 검증을 뜻하지 않습니다. 부문은 제목 키워드로 분류합니다. 내부 개인정보 미사용 · 자동 메일 발송 미설정.</p></section>
<noscript><p class="notice">부문 탭을 사용하려면 브라우저에서 JavaScript를 허용해 주세요.</p></noscript></main><script>{script}</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding='utf-8')
