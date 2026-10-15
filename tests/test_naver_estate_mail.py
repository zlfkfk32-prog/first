from dataclasses import replace
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from cardletter.news import Article, Card, Coverage
from cardletter import naver
from cardletter.estate import GROUPS, regions, prepare, digest
from cardletter.html import render
from cardletter.mail import send_briefing, build_payload
from cardletter.__main__ import main

NOW = datetime(2026, 10, 15, 8, tzinfo=ZoneInfo('Asia/Seoul'))
TITLE = '서울 아파트 공사현장 공정 일정 점검'
BODY = ('공사현장의 공정과 입주 일정을 확인하는 기사이며 사업장 관계자의 설명을 통해 공사비와 향후 진행 상황을 점검한다. ' * 3)


def card(title=TITLE, url='https://publisher.example/news/1'):
    return Card(Article(title, url, '공개매체', NOW, 'NAVER', source_url='https://publisher.example'), GROUPS[1], '공정·지역·사업장 확인', 120, summary=BODY[:100], summary_url=url, summary_kind='본문 발췌')


class Response:
    status = 200
    headers = {'Content-Type': 'text/html; charset=utf-8'}
    def __init__(self, data, url='https://publisher.example/news/1'):
        self.data, self.url = data, url
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self,n): return self.data[:n]
    def geturl(self): return self.url


class NaverTests(unittest.TestCase):
    def test_only_valid_original_news_items_are_kept(self):
        item = {'title': '<b>서울</b> 아파트 공사현장 점검', 'description': '공개 기사', 'originallink': 'https://publisher.example/news/1', 'link': 'https://news.naver.com/1', 'pubDate': 'Thu, 15 Oct 2026 07:00:00 +0900'}
        invalid = [dict(item, originallink=''), dict(item, originallink='https://news.naver.com/a'), dict(item, originallink='https://www.molit.go.kr/press/1'), dict(item,title='[보도자료] 서울 아파트 공사'), dict(item,pubDate='invalid'), dict(item,originallink='https://127.0.0.1/a')]
        result = naver.parse_items({'items': [item,*invalid]}, '수도권 부동산')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].title,'서울 아파트 공사현장 점검')
        self.assertEqual(result[0].url,item['originallink'])

    def test_missing_credentials_never_call_api(self):
        with patch.dict(os.environ, {}, clear=True), patch('cardletter.naver.build_opener') as opener:
            items, coverage = naver.collect(24)
        opener.assert_not_called()
        self.assertFalse(items)
        self.assertFalse(coverage[0].ok)

    def test_verified_original_kept_broken_or_press_release_removed(self):
        data = f'<html><meta property="og:title" content="{TITLE}"><article><p>{BODY}</p></article></html>'.encode()
        with patch('cardletter.naver.build_opener') as factory:
            factory.return_value.open.return_value = Response(data)
            verified,reason = naver.verify_card(card())
            self.assertIsNotNone(verified)
            self.assertEqual(reason,'')
            factory.return_value.open.side_effect = TimeoutError()
            verified,_ = naver.verify_card(card())
            self.assertIsNone(verified)
        press = data.replace(BODY.encode(),('보도자료 제공 ' + BODY).encode())
        with patch('cardletter.naver.build_opener') as factory:
            factory.return_value.open.return_value = Response(press)
            verified,reason = naver.verify_card(card())
            self.assertIsNone(verified)
            self.assertIn('보도자료',reason)

    def test_soft_404_or_other_article_is_removed(self):
        data = ('<html><title>페이지를 찾을 수 없습니다</title><article><p>' + BODY + '</p></article></html>').encode()
        with patch('cardletter.naver.build_opener') as factory:
            factory.return_value.open.return_value = Response(data)
            self.assertIsNone(naver.verify_card(card())[0])

    def test_release_marker_in_metadata_and_body(self):
        for text in ('<meta name="genre" content="Press Release">', '<article>보도 자료 제공 내용</article>', '<script type="application/ld+json">{"genre":"보도자료"}</script>'):
            self.assertTrue(naver.press_release(text.encode(),TITLE))
        self.assertFalse(naver.press_release(('<article>'+BODY+'</article>').encode(),TITLE))

    def test_naver_auth_headers_and_endpoint_with_mocked_transport(self):
        with patch.dict(os.environ, {'NAVER_CLIENT_ID': 'fake-test-id', 'NAVER_CLIENT_SECRET': 'fake-test-secret'}), patch('cardletter.naver.build_opener') as factory:
            factory.return_value.open.side_effect = lambda req,timeout: Response(b'{"items":[]}', req.full_url)
            articles,coverage = naver.collect(24)
        self.assertFalse(articles)
        self.assertTrue(all(c.ok for c in coverage))
        self.assertEqual(len(coverage),4)
        for call in factory.return_value.open.call_args_list:
            request = call.args[0]
            self.assertTrue(request.full_url.startswith(naver.ENDPOINT+'?'))
            self.assertIn('X-naver-client-secret', request.headers)


class EstateTests(unittest.TestCase):
    def test_four_menus_and_pf_regions_preserve_home_structure(self):
        cards = [card('서울 부동산 PF 점검'),card('부산 부동산 PF 점검'),card('전국 부동산 PF 점검')]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'news.html';render(path,cards,[],NOW)
            soup=BeautifulSoup(path.read_text(),'html.parser')
            self.assertEqual([h.get_text() for h in soup.select('#home h2')],['메인 이슈','부문별로 찾아보기','오늘의 핵심'])
            self.assertEqual([a.get_text() for a in soup.select('nav a[href^="#section-"]')],list(GROUPS))
            self.assertIn('수도권 PF',soup.select_one('#section-3').get_text())
            self.assertIn('비수도권 PF',soup.select_one('#section-3').get_text())
            self.assertIn('지역 미확인 PF',soup.select_one('#section-3').get_text())
            for old in ('캐피탈업권','기업금융·IB','IT·디지털'):
                self.assertNotIn(old,soup.get_text())
            self.assertEqual(len(soup.select('#details section')),4)
            self.assertIn('justify-content:center',soup.style.get_text())

    def test_regions_do_not_treat_every_unknown_as_nonmetro(self):
        self.assertEqual(regions('경기 침체 속 전국 부동산 PF'),())
        self.assertEqual(regions('경기 광주 아파트 착공'),('수도권',))
        self.assertEqual(regions('광주광역시 공사현장'),('비수도권',))
        self.assertEqual(regions('서울 부산 부동산 PF'),('수도권','비수도권'))

    def test_major_issue_precedes_routine_and_future_news_excluded(self):
        from cardletter.rankings import demo_roster
        articles=[card('샘플건설057 부산 현장 하자 발생').article,card('서울 부동산 PF 점검','https://publisher.example/news/2').article,replace(card().article,published=NOW+timedelta(hours=1))]
        selected=prepare(articles,NOW,24,demo_roster(2026))
        self.assertIn('하자 발생',selected[0].article.title)
        self.assertEqual(len(selected),2)
        self.assertTrue(all(c.category in GROUPS for c in digest(selected)))

    def test_demo_does_not_call_api_or_send_mail(self):
        with tempfile.TemporaryDirectory() as folder, patch('sys.argv',['cardletter','--demo','--output',folder]), patch('cardletter.__main__.collect') as collector, patch('cardletter.__main__.send_briefing') as mailer:
            self.assertEqual(main(),0)
            collector.assert_not_called();mailer.assert_not_called()
            self.assertTrue(list(Path(folder).glob('*.html')))


class MicrosoftMailTests(unittest.TestCase):
    settings={'M365_TENANT_ID':'fake-tenant','M365_CLIENT_ID':'fake-client','M365_CLIENT_SECRET':'fake-secret','M365_SENDER':'sender@example.com','M365_TO':'reader@example.com'}
    def test_mocked_graph_acceptance_and_local_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,self.settings), patch('cardletter.mail._request_json',side_effect=[(200,{'access_token':'fake-token'}),(202,{})]) as transport:
            pdf=Path(folder)/'brief.pdf';pdf.write_bytes(b'%PDF-1.4 test')
            html=Path(folder)/'brief.html';html.write_text('<html>test</html>')
            result=send_briefing(pdf,html,[card()],NOW,Path(folder)/'state')
            self.assertIn('202',result)
            again=send_briefing(pdf,html,[card()],NOW,Path(folder)/'state')
            self.assertIn('재발송하지',again)
            self.assertEqual(transport.call_count,2)
            payload=json.loads(transport.call_args_list[1].args[1])
            self.assertEqual(len(payload['message']['attachments']),2)
            self.assertIn('sendMail',transport.call_args_list[1].args[0])

    def test_unknown_delivery_result_keeps_pending_marker(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,self.settings), patch('cardletter.mail._request_json',side_effect=[(200,{'access_token':'fake-token'}),TimeoutError()]):
            pdf=Path(folder)/'brief.pdf';pdf.write_bytes(b'%PDF-1.4 test')
            html=Path(folder)/'brief.html';html.write_text('<html>test</html>')
            with self.assertRaisesRegex(ValueError,'중복 방지'):
                send_briefing(pdf,html,[card()],NOW,Path(folder)/'state')
            marker=next((Path(folder)/'state').glob('*.json'))
            self.assertEqual(json.loads(marker.read_text())['state'],'pending')

    def test_unverified_news_cannot_be_mailed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                build_payload(Path(folder)/'x.pdf',Path(folder)/'x.html',[replace(card(),summary_url='')],NOW,'sender@example.com',['reader@example.com'])
