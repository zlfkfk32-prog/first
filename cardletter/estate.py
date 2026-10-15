"""Four-section real estate briefing classification and balanced selection."""
from dataclasses import replace
from difflib import SequenceMatcher
import re
from .news import Card, normalized_title
from .project_focus import major_issue, relevant

GROUPS = ('시공사', '수도권 부동산', '비수도권 부동산', 'PF권역 주요뉴스')
DESCRIPTIONS = ('부도·부실·하자·사고 및 시공 현장 주요 이슈', '서울·경기·인천 사업장·정비사업·분양·공사현장', '수도권 외 지역의 개발사업·현장·분양·미분양', '전국 PF 사업장 소식을 권역별로 구분')
NONMETRO = ('부산', '대구', '광주광역시', '대전', '울산', '세종', '강원', '춘천', '원주', '강릉', '충북', '충남', '충청', '청주', '천안', '아산', '전북', '전남', '전라', '전주', '여수', '순천', '경북', '경남', '경상', '창원', '김해', '포항', '경주', '제주')
METRO = ('서울', '인천', '경기도', '경기권', '수원', '성남', '용인', '화성', '평택', '고양', '파주', '부천', '안양', '안산', '시흥', '김포', '남양주', '의정부', '양주', '하남', '과천', '광명', '의왕', '군포', '오산', '이천', '안성', '여주')


def regions(title):
    found = []
    if any(w in title for w in METRO) or re.search(r'경기(?:\s*(?:남부|북부|광주|동부|서부)|지역)', title):
        found.append('수도권')
    if any(w in title for w in NONMETRO) or ('광주' in title and not re.search(r'경기\s*광주', title)):
        found.append('비수도권')
    return tuple(found)


def is_pf(title):
    return bool(re.search(r'(?<![a-z])pf(?![a-z])', title.lower()) or any(w in title for w in ('프로젝트파이낸싱', '브리지론', '브릿지론', '본피에프')))


def groups(card):
    title = card.article.title
    result = []
    if card.contractors or any(w in title for w in ('시공사', '건설사', '건설현장', '공사현장', '공사 현장')):
        result.append(GROUPS[0])
    result.extend(GROUPS[1] if r == '수도권' else GROUPS[2] for r in regions(title))
    if is_pf(title):
        result.append(GROUPS[3])
    return tuple(dict.fromkeys(result))


def prepare(articles, as_of, hours, roster=None):
    from datetime import timedelta
    cutoff = as_of - timedelta(hours=hours)
    candidates = []
    for article in articles:
        if not cutoff <= article.published <= as_of or not relevant(article.title, roster):
            continue
        matches = roster.matches(article.title) if roster else ()
        priority = 300 if major_issue(article.title, roster) else 150 if is_pf(article.title) else 110
        card = Card(article, '', '원문의 사업장명·위치·시공사·공정 단계·대주단·발생/의혹 여부를 확인하세요.', priority + max(0, 12 - int((as_of-article.published).total_seconds()/3600)), contractors=tuple(c.name for c in matches), contractor_ranks=tuple(c.rank for c in matches))
        memberships = groups(card)
        if memberships:
            card = replace(card, category=GROUPS[3] if is_pf(article.title) else memberships[0])
            candidates.append(card)
    candidates.sort(key=lambda c: (c.score, c.article.published), reverse=True)
    unique = []
    for c in candidates:
        if any(c.article.url == other.article.url or SequenceMatcher(None, normalized_title(c.article.title), normalized_title(other.article.title)).ratio() >= .84 for other in unique):
            continue
        unique.append(c)
    return unique


def balanced(cards, limit=32, per_group=8):
    result = []
    counts = {g: 0 for g in GROUPS}
    for c in cards:
        memberships = groups(c)
        if any(counts[g] < per_group for g in memberships):
            result.append(c)
            for g in memberships: counts[g] += 1
        if len(result) >= limit: break
    return result


def digest(cards):
    # Fixed A4 slots: contractors 2, metro 1, nonmetro 1, PF 2.
    budgets = dict(zip(GROUPS, (2, 1, 1, 2)))
    result = []
    for c in cards:
        memberships = groups(c)
        # Retain PF as its own slot even when the title names a region/company.
        preferred = (GROUPS[3],) if is_pf(c.article.title) else memberships
        slot = next((g for g in preferred if budgets.get(g, 0)), None)
        if slot:
            result.append(replace(c, category=slot))
            budgets[slot] -= 1
    return result
