# 부동산 Daily News

네 가지 뉴스 부문만 제공하는 부동산 사업장 데일리 뉴스레터입니다.

1. **시공사** — 부도·부실·하자·사고·회생·공사 중단 및 현장 소식
2. **수도권 부동산** — 서울·경기·인천의 사업장·정비사업·분양·공사현장
3. **비수도권 부동산** — 수도권 밖 지역의 개발·분양·입주·미분양
4. **PF권역 주요뉴스** — 전국 PF를 수도권·비수도권·지역 미확인으로 구분

기존 홈 틀(메인 이슈 → 부문별로 찾아보기 → 오늘의 핵심), 가운데 메뉴, 부문 탭 이동, 검색, 뉴스 제목/요약 및 오른쪽 아래 원문 링크는 유지합니다. 부문별 기사·수집 상태는 해당 탭에서 봅니다. 주요 부도·부실·하자·사고 보도는 홈 메인 우선입니다. 예방 캠페인·주가 붕괴 등을 사건 발생으로 오인하지 않도록 제목 규칙으로 구분하며, 이 규칙은 독립적인 사실 확인을 뜻하지 않습니다.

## 현재 완료/미완료 범위

- 네 개 부문, A4 PDF·상세 HTML·JSON 생성, NAVER 연동 코드와 원문 검증, Microsoft 365 발송 코드와 예약 설정 예제를 준비했습니다.
- 요청에 따라 **실제 NAVER API 호출과 실제 메일 발송은 하지 않았습니다.** 가상 데이터와 모의 HTTP/Graph 응답으로 검증했습니다.
- 예약 작업은 활성화하지 않았습니다. NAVER 키·회사 앱 권한·발신/수신 설정도 아직 제공되지 않았습니다.
- 기존 Google RSS/공식기관 게시판 수집 코드는 호환 테스트용으로 일부 남아 있지만 `run.py`의 실제 수집 경로는 NAVER API뿐입니다. NAVER 실패 시 다른 소스로 대체하지 않습니다.

## Windows 실행

Python **3.12**가 필요합니다. 전체 ZIP을 풀고 `run.py`, `requirements.txt`가 있는 폴더에서 명령창을 엽니다.

```cmd
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py --demo
explorer output
```

`--demo`는 네트워크/API/메일을 사용하지 않습니다. 샘플 기사·회사·순위·요약은 가상입니다.

생성 파일:

- `output/cardletter-YYYY-MM-DD-sample.pdf` — A4 한 장
- `output/cardletter-YYYY-MM-DD-sample.html` — 메뉴·탭·검색이 있는 브라우저 상세판
- `output/cardletter-YYYY-MM-DD-sample.json` — 선정 기사·출처/제외 통계

HTML은 CSS와 JavaScript를 내장하므로 파일 하나만 브라우저에서 열면 됩니다. 상세 웹페이지 HTML을 이메일 본문에 그대로 붙이는 용도로 보장하지 않습니다.

Mac/Linux에서는 `python3 -m venv .venv` 후 `.venv/bin/python`을 사용합니다. `run.py`는 다른 폴더에서 실행해도 프로젝트 폴더로 이동한 뒤 실행합니다.

## NAVER 설정 — 나중에 실제 수집이 필요할 때만

현재 작업 중에는 API를 호출하지 않았습니다. 아래 실제 실행 명령은 사용자 환경에서 **NAVER API와 기사 원문에 접속**합니다.

1. [NAVER 개발자센터](https://developers.naver.com/) → Application → 애플리케이션 등록에서 **검색 API**를 신청합니다.
2. 발급된 Client ID/Client Secret을 채팅·소스코드에 붙여 넣지 마세요.
3. `.env.example`을 `.env`로 복사하고, `run.py` 옆 `.env`에 아래 두 값을 로컬에서 입력합니다.

```dotenv
NAVER_CLIENT_ID=발급받은값
NAVER_CLIENT_SECRET=발급받은값
```

`.env`와 `.env.*`는 Git에서 제외됩니다. 운영 환경/CI 환경변수는 `.env` 값보다 우선합니다. `--check-config`는 값 대신 설정 유무만 표시하며 외부 호출을 하지 않습니다.

```cmd
.venv\Scripts\python.exe run.py --check-config
```

실제로 수집하려는 경우에만 다음을 실행합니다.

```cmd
.venv\Scripts\python.exe run.py
```

조회는 최근 24시간, 한국시간 기준입니다. `--hours 72`처럼 1~168시간을 지정할 수 있습니다. 쿼리당 NAVER 최신 100건만 조회하므로 긴 기간·다량 기사·모든 지역/시공사에 대한 완전한 수집을 보장하지 않습니다. 지역은 제목에 명시된 지명 기준입니다. '경기 침체'를 경기도로 분류하거나 위치가 없는 기사를 비수도권으로 추정하지 않습니다. 서로 다른 지역이 함께 나오면 중복 표시될 수 있습니다.

## 원문 링크 및 보도자료 제외

NAVER 뉴스 검색 API `https://openapi.naver.com/v1/search/news.json`만 호출합니다. 결과의 `originallink`가 있어야 하며 NAVER 중계 링크로 대체하지 않습니다. HTTP 원문 주소는 HTTPS로 접속을 시도해 확인합니다.

최종 선정 전에 원문 GET 접속, HTTP 200·HTML 여부, 공개 HTTPS·리디렉션 출처, API 제목과 원문 제목의 유사도, 본문/언론사 설명 추출을 검사합니다. 접속 오류·제목 불일치·본문 확인 실패·누락된 링크·공공기관 직접 발표는 최종 기사에서 제외합니다. 후보 검증은 최대 80건으로 제한하고 최종 HTML은 최대 32건입니다. PDF는 시공사 2, 수도권 1, 비수도권 1, PF 2칸으로 최대 6건을 담습니다. 조건을 통과한 기사가 부족하면 빈칸 상태를 표시합니다.

검색 제목·설명과 원문 본문/메타정보/구조화 데이터에서 보도자료·Press Release·뉴스와이어·업체/자료 제공·홍보 표시를 찾아 제외합니다. 표시되지 않은 보도자료 재배포를 완벽하게 판별할 수는 없으며 보수적 필터 때문에 일반 기사도 누락될 수 있습니다. 원문은 검사 이후 삭제·로그인 전환·접속 차단될 수 있습니다. 제외 이유와 수집 상태는 JSON 및 수집 상태 탭에 기록합니다.

요약은 공개 본문/언론사 설명에서 최대 480자·2문장을 발췌합니다. PDF와 홈은 짧게 표시합니다. 업무 확인점·용어 설명은 일반 참고 안내로 구분하며 숫자·사업장 위치·시공사 관계를 추정하지 않습니다. 회사 내부 개인정보는 사용하지 않습니다.

## 매일 오전 8시 Microsoft 365/Outlook 메일

**기술적으로 가능합니다. 다만 현재 실제 발송은 설정/검증하지 않았습니다.** Outlook 프로그램을 켜 놓는 방식 대신 Microsoft Graph 앱 인증으로 보냅니다.

회사 Microsoft 365 관리자에게 다음을 확인하세요.

- Microsoft Entra ID 앱 등록과 테넌트/클라이언트 ID, 클라이언트 비밀 또는 회사가 허용하는 인증 방식
- Microsoft Graph **Mail.Send 애플리케이션 권한**에 대한 관리자 동의
- 허용한 발신 사서함으로 권한 범위를 제한하는 회사 Exchange/Entra 정책
- 지정 수신자에게 PDF/HTML 첨부 발송이 가능한지 여부. HTML 첨부는 회사 보안 정책에서 차단될 수 있습니다.

이 구현은 클라이언트 비밀 기반 앱 인증 예제입니다. 회사가 해당 방식을 금지하면 관리자가 승인한 인증 방식으로 변경해야 합니다. API 키·비밀·수신자 목록은 `.env` 또는 GitHub Actions Secrets에만 설정합니다.

```dotenv
M365_TENANT_ID=회사테넌트ID
M365_CLIENT_ID=앱클라이언트ID
M365_CLIENT_SECRET=앱비밀
M365_SENDER=발신사서함주소
M365_TO=수신주소1,수신주소2
```

메일 설정 유무 확인은 `--check-config`로 합니다. **실제 발송을 의도할 때만** 다음 명령을 실행합니다.

```cmd
.venv\Scripts\python.exe run.py --send-email
```

NAVER로 수집하고 원문 검증을 통과한 기사가 있을 때만 PDF·상세 HTML을 첨부하고 메일 본문에는 핵심 기사 3건을 넣습니다. 가상 데이터 발송은 거부합니다. HTTP 202는 Graph가 요청을 접수한 뜻이며 수신함 도착 보장이 아닙니다. 외부 발송 권한·DLP/메일 규칙·전달 결과는 회사 관리자 확인이 필요합니다.

`output/.mail-state`에 날짜/대상 해시별 pending/accepted 기록을 남겨 중복을 줄입니다. 접수 결과가 불명확하면 자동 재발송하지 않습니다. 보낸 편지함/관리자 추적 후 처리하세요. 이 폴더를 삭제하면 중복 방지가 초기화됩니다. 다른 PC나 저장 상태가 유지되지 않는 환경의 중복 방지는 보장하지 않습니다.

### 예약 방법 1: GitHub Actions

`.github/workflows/daily-cardletter.yml`은 매일 **23:00 UTC = 다음 날 08:00 KST**를 목표로 합니다. GitHub 예약은 지연될 수 있어 정각 8시 발송을 보장하지 않습니다. 일정이 정확해야 하면 회사가 운영하는 상시 실행 서버·Azure 스케줄러 등을 권장합니다.

자동 실행을 켜려면 기본 브랜치에 워크플로를 반영하고 Actions를 허용한 후 Secrets에 위 NAVER/M365 설정을 등록합니다. Variables에서 `ENABLE_DAILY_NEWS=true`를 설정해야 예약 수집하며, 별도로 `ENABLE_DAILY_EMAIL=true`를 설정해야 발송합니다. **기본은 둘 다 비활성**입니다. 수동 실행도 기본은 demo이므로 API/발송이 없습니다.

같은 날짜의 상태를 Actions cache에 저장/복원해 재실행 중복을 줄입니다. 캐시 유실·다른 브랜치/호스트·동시 실행 등으로 인한 중복 가능성은 남습니다. 캐시에는 비밀이나 수신자 주소를 쓰지 않습니다.

### 예약 방법 2: Windows 작업 스케줄러

샘플 파일 `scripts/register_daily_task.ps1`은 현재 사용자에게 매일 **Windows 로컬시간 08:00** 작업을 등록합니다. Windows 시간대가 한국시간인지 확인하세요. 실제 등록은 자동으로 하지 않았습니다. 키·회사 권한·수신 설정을 마치고 실제 발송을 승인한 경우에만 PowerShell에서 직접 실행하세요.

```powershell
powershell -File .\scripts\register_daily_task.ps1
```

현재 사용자 로그인·PC 전원·인터넷이 필요하며 PC가 꺼져 있거나 절전이면 제시간에 발송되지 않을 수 있습니다. 작업 이름은 `RealEstateDailyNews`입니다. 회사 정책을 우회해 실행 정책을 변경하지 마세요.

## 시공사 명단과 검증

기존 공식 2026년 토목건축공사업 TOP100 명단·원본·체크섬 및 갱신 도구는 유지합니다. NAVER 공개 검색으로 다른 시공사도 조회하며, 공식 명단에 대조된 회사만 순위를 표시합니다. 회사명 경계를 확인하고 명단 밖 순위는 추정하지 않습니다.

```cmd
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

테스트는 API·원문·메일 응답을 모의 처리하며 실제 NAVER/메일 서비스로 접속하거나 전송하지 않습니다. 가상 샘플은 `examples/detailed-sample.html`에도 있습니다.
