"""Optional Microsoft 365 Graph delivery. No calls unless explicitly requested."""
import base64
from datetime import datetime
from email.utils import getaddresses
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

MAIL_SETTINGS = ('M365_TENANT_ID', 'M365_CLIENT_ID', 'M365_CLIENT_SECRET', 'M365_SENDER', 'M365_TO')


def check_settings():
    missing = []
    for name in MAIL_SETTINGS:
        present = bool(os.getenv(name))
        print(name + ': ' + ('설정됨' if present else '설정 필요'))
        if not present: missing.append(name)
    return missing


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('메일 인증/API 리디렉션 거부')


def _request_json(url, payload, headers):
    request = Request(url, data=payload, headers=headers, method='POST')
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000: raise ValueError('메일 API 응답 크기 초과')
        return response.status, json.loads(data) if data else {}


def email_body(cards, as_of):
    items = []
    for c in cards[:3]:
        url = escape(c.summary_url or c.article.url, quote=True)
        items.append(f'<div style="border:1px solid #ddd;padding:14px;margin:12px 0"><h3>{escape(c.article.title)}</h3><p>{escape(c.summary[:180])}</p><p style="text-align:right"><a href="{url}">원문 보기</a></p></div>')
    return f'<div style="font-family:Malgun Gothic,sans-serif;max-width:680px;margin:auto"><h2>{as_of:%Y/%m/%d} Daily News</h2><p>시공사 · 수도권 부동산 · 비수도권 부동산 · PF권역 주요뉴스</p>' + ''.join(items) + '<p>한 장 요약은 첨부 PDF, 메뉴가 있는 상세 뉴스는 첨부 HTML을 저장하여 브라우저에서 확인하세요.</p></div>'


def build_payload(pdf_path, html_path, cards, as_of, sender, recipients):
    if not cards or any(not c.summary_url or not c.summary for c in cards):
        raise ValueError('원문 검증을 통과한 기사만 발송할 수 있습니다')
    attachments = []
    for path, content_type in ((pdf_path, 'application/pdf'), (html_path, 'text/html')):
        data = Path(path).read_bytes()
        attachments.append({'@odata.type': '#microsoft.graph.fileAttachment', 'name': Path(path).name, 'contentType': content_type, 'contentBytes': base64.b64encode(data).decode('ascii')})
    payload = {'message': {'subject': f'[{as_of:%Y.%m.%d}] 부동산 Daily News', 'body': {'contentType': 'HTML', 'content': email_body(cards, as_of)}, 'toRecipients': [{'emailAddress': {'address': address}} for address in recipients], 'attachments': attachments}, 'saveToSentItems': True}
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if len(raw) > 3_000_000: raise ValueError('메일 첨부 크기 제한 초과; 분할 또는 별도 저장 필요')
    return raw


def send_briefing(pdf_path, html_path, cards, as_of, state_dir):
    missing = [name for name in MAIL_SETTINGS if not os.getenv(name)]
    if missing: raise ValueError('메일 설정 필요: ' + ', '.join(missing))
    if Path(pdf_path).read_bytes()[:5] != b'%PDF-': raise ValueError('첨부 PDF 형식 오류')
    sender = os.environ['M365_SENDER'].strip()
    raw_recipients = os.environ['M365_TO'].replace(';', ',')
    recipients = [address for _,address in getaddresses([raw_recipients])]
    if not recipients or any('@' not in address or '\n' in address or '\r' in address for address in [sender,*recipients]):
        raise ValueError('발신/수신 주소 형식 확인 필요')
    tenant = os.environ['M365_TENANT_ID']
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.' for c in tenant):
        raise ValueError('M365_TENANT_ID 형식 확인 필요')
    payload = build_payload(pdf_path, html_path, cards, as_of, sender, recipients)
    identity = sha256((sender.lower() + '|' + '|'.join(sorted(a.lower() for a in recipients))).encode()).hexdigest()[:16]
    state_dir = Path(state_dir);state_dir.mkdir(parents=True, exist_ok=True)
    marker = state_dir / f'{as_of:%Y-%m-%d}-{identity}.json'
    if marker.exists(): return '동일 날짜·발신/수신 대상의 발송 기록 또는 처리 중 기록이 있어 재발송하지 않았습니다'
    # Fetch a token first; failure here cannot have submitted an email.
    token_data = urlencode({'client_id': os.environ['M365_CLIENT_ID'], 'client_secret': os.environ['M365_CLIENT_SECRET'], 'scope': 'https://graph.microsoft.com/.default', 'grant_type': 'client_credentials'}).encode()
    try:
        _, token = _request_json('https://login.microsoftonline.com/' + tenant + '/oauth2/v2.0/token', token_data, {'Content-Type': 'application/x-www-form-urlencoded'})
        access = token['access_token']
    except Exception:
        raise ValueError('Microsoft 365 인증 실패; 앱 설정·회사 관리자 동의를 확인하세요') from None
    try:
        with marker.open('x', encoding='utf-8') as handle: json.dump({'state': 'pending', 'date': as_of.strftime('%Y-%m-%d')}, handle)
    except FileExistsError:
        return '다른 실행이 이미 발송을 처리 중이므로 중복 발송하지 않았습니다'
    try:
        status, _ = _request_json('https://graph.microsoft.com/v1.0/users/' + quote(sender, safe='') + '/sendMail', payload, {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + access})
        if status != 202: raise ValueError('메일 접수 상태 확인 필요')
    except Exception:
        # Network timeout can happen after the service accepted the request: keep pending.
        raise ValueError('메일 요청 결과 확인 필요. 중복 방지를 위해 기록을 유지했습니다. 보낸 편지함/관리자 추적을 확인하세요') from None
    marker.write_text(json.dumps({'state': 'accepted', 'date': as_of.strftime('%Y-%m-%d')}), encoding='utf-8')
    return 'Microsoft 365가 발송 요청을 접수했습니다(HTTP 202). 수신함 도착 보장은 아니며 전달 상태는 회사 메일 추적으로 확인하세요'
