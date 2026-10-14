"""Standalone email-style public news briefing, generated alongside the PDF."""
from html import escape
from pathlib import Path
from datetime import datetime
from .news import Card, Coverage

GROUPS = ('부동산 PF·정책', '업권 공통·캐피탈', '기업금융·IB', '개인·리테일 금융', '투자', '리스크관리', 'IT·디지털', 'TOP100 시공사')


def groups(card: Card) -> tuple[str, ...]:
    primary = {'캐피탈업권': GROUPS[1], '개인·리테일 금융': GROUPS[3], 'TOP100 시공사': GROUPS[7]}.get(card.category, GROUPS[0])
    title = card.article.title.lower()
    result = [primary]
    for label, words in (
        (GROUPS[2], ('인수금융', '기업금융', '기업대출', 'ib', '인수합병')),
        (GROUPS[4], ('투자', '펀드', '지분', '매각')),
        (GROUPS[5], ('연체', '부실', '신용', '유동성', '건전성', '위험', '리스크', '안전', '사고')),
        (GROUPS[6], ('해킹', '정보 유출', '정보유출', '디지털', '전산', '보안', '인공지능', ' ai', 'ax ')),
    ):
        if any(word in title for word in words) and label not in result:
            result.append(label)
    return tuple(result)


def article_box(card: Card, as_of: datetime, demo: bool) -> str:
    title = escape(card.article.title)
    body = escape(card.summary or '요약 보류 · 원문을 확인하지 못했습니다.')
    meta = escape(card.article.publisher + ' · ' + card.article.published.astimezone(as_of.tzinfo).strftime('%m.%d'))
    if card.contractor_ranks:
        meta += ' · 시평 ' + ', '.join(str(rank) for rank in card.contractor_ranks) + '위'
    content = f'<strong style="font-size:15px;line-height:1.5">{title}</strong><div style="font-size:13px;color:#5A6375;line-height:1.6;margin-top:6px">{body}</div><div style="font-size:11px;color:#5A6375;margin-top:8px">{meta}</div>'
    style = 'display:block;padding:14px;text-decoration:none;color:#1A1A1A;background:#F6F7FA;margin:8px 0;border-radius:6px'
    if demo:
        return f'<div style="{style}">{content}</div>'
    url = escape(card.summary_url or card.article.url, quote=True)
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer" style="{style}">{content}</a>'


def render(path: Path, cards: list[Card], coverage: list[Coverage], as_of: datetime, demo: bool = False) -> None:
    weekday = ('월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일')[as_of.weekday()]
    title = f'{as_of:%Y/%m/%d}/{weekday} Daily News'
    buckets = {label: [card for card in cards if label in groups(card)] for label in GROUPS}
    lead = article_box(cards[0], as_of, demo) if cards else '<p>선정 기사 없음 · 수집 상태를 확인하세요.</p>'
    tiles = []
    for i, label in enumerate(GROUPS):
        tiles.append(f'<td width="50%" style="padding:5px"><a href="#section-{i}" style="display:block;padding:10px;background:#F6F7FA;color:#1F3A68;text-decoration:none;text-align:center;font-size:12px">{label}<br><b style="font-size:18px">{len(buckets[label])}건</b></a></td>')
    rows = ''.join('<tr>' + ''.join(tiles[i:i+2]) + '</tr>' for i in range(0, len(tiles), 2))
    details = []
    for i, label in enumerate(GROUPS):
        contents = ''.join(article_box(card, as_of, demo) for card in buckets[label]) or '<p style="font-size:13px;color:#5A6375">오늘 선정 기사 중 해당 부문 뉴스가 없습니다.</p>'
        details.append(f'<section id="section-{i}" style="margin-top:22px"><h2 style="font-size:16px;color:#1F3A68;border-bottom:2px solid #1F3A68;padding-bottom:7px">{label} · {len(buckets[label])}건</h2>{contents}</section>')
    status = ' / '.join(escape(c.name) + (' 가상 예시' if demo else f' {c.count}건' if c.ok else ' 수집 미완료') for c in coverage)
    notice = '디자인 샘플 · 기사·순위·요약 모두 가상 예시' if demo else '공개정보 기반 · 본문 미확인 시 요약 보류'
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title></head>
<body style="margin:0;padding:18px 10px;background:#E9ECF1;font-family:'Malgun Gothic',sans-serif;color:#1A1A1A">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;margin:auto;background:white"><tr><td style="background:#1F3A68;padding:20px;color:white"><h1 style="font-size:23px;margin:0">{title}</h1><p style="font-size:12px;margin-bottom:0">부동산 PF · 캐피탈 · 개인/리테일 · TOP100 시공사</p></td></tr>
<tr><td style="padding:20px"><div style="font-size:12px;color:#9C4A3C">{notice}</div><h2 style="font-size:16px;color:#1F3A68">메인 이슈</h2>{lead}
<h2 style="font-size:16px;color:#1F3A68">부문별 브리핑</h2><table role="presentation" width="100%">{rows}</table>
<p style="font-size:11px;color:#5A6375">최종 선정 {len(cards)}건 기준 · 한 기사는 여러 부문에 표시될 수 있습니다. 전체 수집 기사 수 또는 전일 대비 수치가 아닙니다. 부문을 누르면 상세 내용으로 이동하고 뉴스 박스를 누르면 원문으로 연결됩니다.</p>
<h2 style="font-size:16px;color:#1F3A68">오늘의 핵심</h2>{''.join(article_box(card, as_of, demo) for card in cards[:3])}
<div style="background:#F6F7FA;padding:12px;font-size:13px"><a href="#section-7" style="color:#2A6F7F">시공사 동향 · 공식 TOP100 대상 선정 {len(buckets[GROUPS[7]])}건</a></div>
{''.join(details)}<p style="border-top:1px solid #E3E6EC;padding-top:15px;font-size:11px;color:#5A6375;line-height:1.6">수집 상태: {status}<br>부문 추가 분류는 제목 키워드 기준이며 요약과 별개입니다. 내부 개인정보 미사용 · 메일 발송 미설정 · 생성 기준 {as_of:%Y.%m.%d %H:%M} KST</p></td></tr></table></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding='utf-8')
