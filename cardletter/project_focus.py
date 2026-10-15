"""Project-focused rules; relevance and alerts are headline signals, not fact verification."""
import re

PROJECT_WORDS = ('부동산', '사업장', '공사현장', '공사 현장', '건설', '시공', '아파트', '주택', '재개발', '재건축', '정비사업', '물류센터', '데이터센터', '산업단지', '도시개발', '분양', '미분양', '착공', '준공', '공사비', '공정률', '택지')
ISSUES = ('부도', '파산', '법정관리', '회생절차', '회생신청', '회생 신청', '워크아웃', '부실', '하자', '붕괴', '사망', '중대재해', '화재', '사고', '공사중단', '공사 중단', '지급불능', '채무불이행')
NEGATIONS = ('예방', '방지', '대비', '훈련', '교육', '캠페인', '무사고', '제로', '사고 없는', '부도설 부인', '부도설 일축', '막는다', '막는', '우려', '가능성', '박람회')


def relevant(title: str, roster=None) -> bool:
    matches = roster.matches(title) if roster else ()
    context = title
    # A company name containing '건설' does not make personnel or publicity a site story.
    names = [name for company in matches for name in (company.name, *company.aliases)]
    for name in sorted(names, key=len, reverse=True):
        context = context.replace(name, '')
    return bool(any(w in context for w in PROJECT_WORDS) or re.search(r'(?<![a-z])pf(?![a-z])', context.lower()) or (matches and any(w in context for w in ('부도', '파산', '법정관리', '회생', '워크아웃', '부실', '하자', '채무불이행', '지급불능', '수주', '낙찰', '공사', '신용등급'))))


def major_issue(title: str, roster=None) -> bool:
    if not relevant(title, roster) or not any(w in title for w in ISSUES):
        return False
    # Avoid promoting routine prevention campaigns as incidents.
    if any(w in title for w in NEGATIONS) and not any(w in title for w in ('발생', '숨져', '사망', '붕괴', '신청', '중단', '판결')):
        return False
    return True


def classify_project(article, roster=None):
    title = article.title
    if not relevant(title, roster):
        return None
    lower = title.lower()
    contractor = bool(roster and roster.matches(title))
    checkpoint = '사업장 위치·시행사·시공사·공정·자금조달·보도 기준일을 원문에서 확인하세요.'
    if major_issue(title, roster):
        return ('TOP100 시공사' if contractor else '시공사·신용', '부도·부실·하자·사고 관련 보도입니다. 발생 사업장·피해 범위·확정/의혹 여부·후속 조치를 원문에서 구분해 확인하세요.', 300)
    if any(w in lower for w in ('pf', '프로젝트파이낸싱')):
        return '부동산 PF', '사업장별 브리지론·본PF 전환·만기·상환재원·채무보증 조건을 확인하세요.', 150
    if contractor:
        return 'TOP100 시공사', checkpoint, 100
    if any(w in title for w in ('캐피탈', '여전', '금융사')) and any(w in title for w in ('대출', '조달', '담보', '채권')):
        return '캐피탈업권', '해당 부동산 사업장의 대주단·대출 조건·담보·만기를 확인하세요.', 130
    if any(w in title for w in ('입주', '전세대출', '분양', '미분양', '공정률', '착공', '준공')):
        return '개인·리테일 금융', '지역·사업장명·공정 단계·분양/미분양·입주 일정을 원문에서 확인하세요.', 115
    if any(w in title for w in ('인수', '매각', '경매', '공매', '부실채권')):
        return '기업금융·IB', '사업장 매각·인수·채권 정리 조건과 거래 완료 여부를 확인하세요.', 125
    if any(w in title for w in ('펀드', '리츠', '투자')):
        return '투자', '개발사업 투자 대상·토지 확보·인허가·회수 조건을 확인하세요.', 115
    if any(w in title for w in ('스마트건설', '스마트 건설', 'bim', 'BIM', '디지털', '안전기술')):
        return 'IT·디지털', '공사현장 기술 적용 범위·시행 시점·안전 관리 효과의 근거를 확인하세요.', 90
    if any(w in title for w in ('조달', '담보', '대출', '금융')):
        return '부동산 금융', checkpoint, 135
    if article.official and any(w in title for w in ('정책', '규제', '허가', '공급', '건설')):
        return '정책·감독', '사업장 인허가·안전·공급 정책의 대상 지역과 적용 시점을 확인하세요.', 120
    if any(w in title for w in ('연체', '충당금', '보증', '신용등급')):
        return '리스크관리', checkpoint, 125
    return '개인·리테일 금융', '지역·사업장명·공정 단계·분양/미분양·입주 일정과 수치를 원문에서 확인하세요.', 110
