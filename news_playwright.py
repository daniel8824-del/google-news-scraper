# Playwright Stealth 기반 뉴스 추출 API (v3.0)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, HttpUrl
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth
from bs4 import BeautifulSoup
import json
import re
import os
import uvicorn

# ============================================================================
# 뉴스 본문 정제 함수
# ============================================================================
def clean_news_body(raw_content: str) -> str:
    """
    뉴스 본문에서 메타데이터, 기자 정보, UI 요소 등을 제거하는 함수
    JavaScript cleanNewsBody 함수의 Python 버전 (완전 동기화)
    """
    if not raw_content:
        return raw_content
    if not isinstance(raw_content, str):
        return raw_content
    if len(raw_content) < 50:
        return raw_content
    
    # Firewall 차단 메시지 감지 - empty 반환
    if re.search(r'The request.*?contrary to the Web firewall', raw_content, re.I):
        return ''
    
    # 1단계: 전처리 - 인라인 패턴 치환
    raw_content = re.sub(r'입력\s*\d{4}\.\d{2}\.\d{2}\.\s*\d{2}:\d{2}', '', raw_content)
    raw_content = re.sub(r'업데이트\s*\d{4}\.\d{2}\.\d{2}\.\s*\d{2}:\d{2}', '', raw_content)
    raw_content = re.sub(r'\[By Taboola\][^\n]*', '', raw_content)
    raw_content = re.sub(r'\[AD\][^\n]*', '', raw_content)
    
    # 맥스무비 UI 패턴 제거
    raw_content = re.sub(r'\n\d+분\s*이내\n', '\n', raw_content)
    raw_content = re.sub(r'\n글자\s*크기\s*변경\n', '\n', raw_content)
    raw_content = re.sub(r'\n이\s*기사를\s*추천합니다\.?\n', '\n', raw_content)
    
    # 한국경제 UI 패턴 제거
    raw_content = re.sub(r'^[가-힣]+\n입력\n수정\n지면\n[A-Z]\d+\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n[^\n]*\n', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\n싫어요\n후속기사 원해요\n한국경제 구독신청\n모바일한경 보기\n귀 기울여 듣겠습니다\.\s*$', '', raw_content)
    
    # 제목에서 매체명 제거
    raw_content = re.sub(r'\s+채널A\s*뉴스\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\s+MBC\s*뉴스\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\s+KBS\s*뉴스\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\s+SBS\s*뉴스\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\s+YTN\s*$', '', raw_content, flags=re.M)
    
    # 2단계: 블로그 헤더 통째로 제거
    is_blog = bool(re.search(r'루빵루나|URL 복사|본문 기타 기능', raw_content))
    has_share_pattern = bool(re.search(r'공유하기\s*신고하기', raw_content))
    
    if is_blog and has_share_pattern:
        match = re.search(r'공유하기\s*신고하기', raw_content)
        if match:
            share_index = match.start()
            if share_index > 0 and share_index < len(raw_content) * 0.3:
                raw_content = re.sub(r'^[\s\S]*?공유하기\s*신고하기\s*', '', raw_content)
    
    # 3단계: 특수 패턴 전처리
    # 기자 정보 인라인 제거
    raw_content = re.sub(r'\([\s가-힣]*=\s*연합뉴스\)\s*[가-힣\s]+기자\s*[=]*\s*', '', raw_content)
    raw_content = re.sub(r'\([^)]*=\s*[^)]+\)\s*[가-힣\s]+기자\s*[=]*\s*', '', raw_content)
    raw_content = re.sub(r'[가-힣]+기자\s+구독\s+구독중', '', raw_content)
    raw_content = re.sub(r'\[[^\]]*기자\]', '', raw_content)
    raw_content = re.sub(r'\[[^\]]*AI\s*리포터\]', '', raw_content)
    raw_content = re.sub(r'\n[가-힣]{2,4}\s*\n기자\s*[\/]?\s*\n', '\n', raw_content, flags=re.M)
    
    # 뉴시스 스타일 기자 정보 제거
    raw_content = re.sub(r'\[[^\]]+=[^\]]+\][가-힣\s]+기자\s*=\s*', '', raw_content)
    raw_content = re.sub(r'\[[^\]]+=[^\]]+\]\s*[^\n]+\n', '', raw_content)
    raw_content = re.sub(r'◎공감언론\s*뉴시스', '', raw_content)
    
    # 언론사명/프로그램명 단독 라인
    raw_content = re.sub(r'\nOSEN\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\nOSEN\s+DB\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\n아침&\s*소셜픽\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\n[가-힣]{2,4}\s+앵커\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'\n엔터플레이\s*$', '', raw_content, flags=re.M)
    
    # iMBC연예 패턴
    raw_content = re.sub(r'iMBC연예\s+[가-힣]{2,4}\s*\|\s*사진출처[^\n]*', '', raw_content)
    raw_content = re.sub(r'iMBC연예\s+[가-힣]{2,4}\s+사진출처[^\n]*', '', raw_content)
    raw_content = re.sub(r'\niMBC연예\s+[가-힣]{2,4}\s+사진출처[^\n]*', '', raw_content)
    raw_content = re.sub(r'iMBC연예\s+[가-힣]{2,4}', '', raw_content)
    
    # 특파원/기자 패턴 제거 (지역명=이름 특파원/기자)
    raw_content = re.sub(r'^[가-힣]+\s*[=＝]\s*[가-힣\s]+\s*(특파원|기자)\s*\n', '', raw_content, flags=re.M)
    
    # === 보그 코리아 전용 패턴 ===
    raw_content = re.sub(r'^[\*\s]+$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^\(\)\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^korea\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^(최신기사|추천기사|인기기사|더 볼만한 기사)\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^지금 인기 있는 뷰티 기사\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^지금, 보그가 주목하는 인물\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^PEOPLE NOW\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^[^\n]*\(Vogue Korea\)\n\(\)\n(\*\s*\n)+', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^보그 코리아[^\n]*\n\(\)\n(\*\s*\n)+', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^([^\n]{10,})\n\*\s*\n\1\n', r'\1\n', raw_content, flags=re.M)
    raw_content = re.sub(r'\n\*\s+(복사|공유|top)\s*\n', '\n', raw_content)
    raw_content = re.sub(r'^(복사|공유)\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^SNS 공유하기\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^VOGUE\.CO\.KR IS OPERATED BY\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'^top\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'보그 코리아\s*\(Vogue Korea\)[^\n]*\n\(\)\n(\*\s*\n)+[^\n]+\n\*\s*\n[^\n]+\n\*\s*복사\n\*\s*공유\n', '', raw_content)
    
    # 보그 이미지 마크다운 제거
    raw_content = re.sub(r'!\[Image \d+:?\]\([^\)]+\)', '', raw_content)
    raw_content = re.sub(r'\[!\[Image \d+:?[^\]]*\]\([^\)]*\)\]\([^\)]*\)', '', raw_content)
    raw_content = re.sub(r'\n\*\s*공유\s*\n', '\n', raw_content)
    raw_content = re.sub(r'\n\*\s*복사\s*\n', '\n', raw_content)
    raw_content = re.sub(r'\n\*\s*top\s*\n', '\n', raw_content)
    
    # 4단계: 사진/영상 크레딧 제거
    raw_content = re.sub(r'\/사진\s*=\s*[가-힣]+\s*기자', '', raw_content)
    raw_content = re.sub(r'\/\s*사진\s*제공\s*=\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'[▲▼][^\n]*(?:\/사진=|©)[^\n]*', '', raw_content)
    raw_content = re.sub(r'[▲▼]\s*사진\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'[▲▼]\s*출처\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'사진\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'사진제공\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'사진출처\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'\n?\[화면출처\s+[^\]]+\]', '', raw_content)
    
    # 5단계: 방송 대본 마커 제거
    raw_content = re.sub(r'◀\s*(앵커|리포트|기자|인터뷰)\s*▶', '\n', raw_content)
    raw_content = re.sub(r'\[[^\]]+\/[^\]]+\s*\([^)]+\)\]', '', raw_content)
    
    # 6단계: 미디어 메타 정보 제거
    raw_content = re.sub(r'\[사진[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[영상[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[이미지[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[동영상[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[그래픽[^\]]*\]', '', raw_content)
    
    # 7단계: 영상/제보 정보 제거
    raw_content = re.sub(r'영상취재\s*[:：][^\n▷]*', '', raw_content)
    raw_content = re.sub(r'영상편집\s*[:：]?[^\n▷]*', '', raw_content)
    raw_content = re.sub(r'\n영상편집\s+[가-힣]{2,4}\s*$', '', raw_content, flags=re.M)
    raw_content = re.sub(r'영상제공\s*[:：][^\n▷]*', '', raw_content)
    raw_content = re.sub(r'MBC뉴스\s+[가-힣]+입니다\.', '', raw_content)
    raw_content = re.sub(r'▷\s*전화[^\n▷]*', '', raw_content)
    raw_content = re.sub(r'▷\s*이메일[^\n▷]*', '', raw_content)
    raw_content = re.sub(r'▷\s*카카오톡[^\n▷]*', '', raw_content)
    raw_content = re.sub(r'■\s*제보하기', '', raw_content)
    
    # 8단계: 기타 노이즈
    raw_content = re.sub(r'[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '', raw_content)
    raw_content = re.sub(r'이전\s+다음', '', raw_content)
    raw_content = re.sub(r'좋아요\s*응원수', '', raw_content)
    raw_content = re.sub(r'Fn투데이는 여러분의 후원금을 귀하게 쓰겠습니다\.', '', raw_content)
    
    lines = [line.strip() for line in raw_content.split('\n')]
    
    # 9단계: 끝점 찾기 - 특정 패턴 이후 모두 제거
    end_patterns = [
        r'^많이\s*본\s*기사$',
        r'^많이\s*본\s*뉴스$',
        r'^다른\s*기사\s*보기$',
        r'^관련기사$',
        r'^최신기사$',
        r'^추천기사$',
        r'^관련\s*키워드$',
        r'^주요\s*기사$',
        r'^iMBC연예\s*[가-힣]+$',
    ]
    
    for pattern in end_patterns:
        for i, line in enumerate(lines):
            if re.match(pattern, line):
                lines = lines[:i]
                break
        else:
            continue
        break
    
    # 10단계: 라인 필터링
    filtered_lines = []
    for line in lines:
        if not line or len(line) < 2:
            continue
        if line in ['.', '=']:
            continue
        
        # === 한국경제 UI ===
        if re.match(r'^입력$|^수정$', line):
            continue
        if re.match(r'^지면$', line):
            continue
        if re.match(r'^A\d+$', line):
            continue
        if re.match(r'^글자크기\s*조절$', line):
            continue
        if re.match(r'^기사\s*스크랩$', line):
            continue
        if re.match(r'^댓글$', line):
            continue
        if re.match(r'^클린뷰$', line):
            continue
        if re.match(r'^프린트$', line):
            continue
        if re.match(r'^싫어요$', line):
            continue
        if re.match(r'^후속기사\s*원해요$', line):
            continue
        if re.match(r'^한국경제\s*구독신청$', line):
            continue
        if re.match(r'^모바일한경\s*보기$', line):
            continue
        if re.match(r'^귀\s*기울여\s*듣겠습니다\.$', line):
            continue
        
        # === 보그 코리아 ===
        if re.match(r'^\*+\s*$', line):
            continue
        if re.match(r'^\(\)\s*$', line):
            continue
        if re.match(r'^korea$', line):
            continue
        if re.match(r'^Vogue Korea$', line):
            continue
        if re.match(r'^(최신|추천|인기)기사$', line):
            continue
        if re.match(r'^더 볼만한 기사$', line):
            continue
        if re.match(r'^지금 인기 있는 뷰티 기사$', line):
            continue
        if re.match(r'^지금, 보그가 주목하는 인물$', line):
            continue
        if re.match(r'^PEOPLE NOW$', line):
            continue
        if re.match(r'^(복사|공유|top)$', line):
            continue
        if re.match(r'^SNS 공유하기$', line):
            continue
        if re.match(r'^VOGUE\.CO\.KR IS OPERATED BY$', line):
            continue
        if re.match(r'^포토\s+Netflix$', line):
            continue
        if re.match(r'^관련기사$', line):
            continue
        
        # 보그 날짜 패턴
        if re.match(r'^\d{4}\.\d{2}\.\d{2}$', line):
            continue
        
        # 보그 이미지 패턴
        if re.match(r'^Image \d+:', line):
            continue
        if re.match(r'^\[Image \d+', line):
            continue
        if re.match(r'^!\[Image', line):
            continue
        
        # === TJB 대전방송 ===
        if re.match(r'^기자별\s*뉴스$', line):
            continue
        if re.match(r'^NEWS$', line):
            continue
        if re.match(r'^화면\s*프린트$', line):
            continue
        if re.match(r'^TJB\s*(대전)?방송$', line):
            continue
        if re.search(r'시청자들의 생각과 느낌을 담은', line):
            continue
        if re.search(r'더욱 공정하고 신뢰받는 방송이', line):
            continue
        if re.match(r'^전체검색', line):
            continue
        if re.match(r'^열기$', line):
            continue
        if re.match(r'^\(사진=연합뉴스\)$', line):
            continue
        
        # === 채널A ===
        if re.match(r'^\[채널A\s*뉴스\]\s*구독하기$', line):
            continue
        if re.search(r'채널A\s*뉴스', line):
            continue
        if re.match(r'^\[•\s*[가-힣]+\s*기자', line):
            continue
        if re.match(r'^•\s*\[채널A', line):
            continue
        if re.match(r'구독하기$', line):
            continue
        
        # === 조선일보 ===
        if re.search(r'조선일보\s*(국제부|경제부|정치부|사회부)가\s*픽한', line, re.I):
            continue
        if re.search(r'원샷\s*국제뉴스\s*더\s*보기', line, re.I):
            continue
        
        # === 조선일보 칼럼 동영상 UI ===
        if re.match(r'^(Cancel|live|CC|1x|2x|Speed|Subtitles)$', line):
            continue
        if re.match(r'^\d{2}:\d{2}$', line):
            continue
        if re.match(r'^\d{6}\s+여론\d+', line):
            continue
        
        # === 조선일보 뉴스레터/칼럼 끝 ===
        if re.search(r'매일\s*조선일보에\s*실린\s*칼럼', line):
            continue
        if re.search(r'뉴스레터를\s*받아보세요', line):
            continue
        if re.search(r'I\s+Can\'t\s+Go\s+On,?\s+I\'ll\s+Go\s+On', line):
            continue
        if re.search(r'\'5분\s*칼럼\'\s*더보기', line):
            continue
        if re.search(r'\(사무엘\s*베켓\)', line):
            continue
        
        # === 조선일보 해시태그/구독 정보 ===
        if re.match(r'^#[가-힣a-zA-Z0-9\s-]+$', line):
            continue
        if re.match(r'^구독수$', line):
            continue
        if re.match(r'^구독$', line):
            continue
        if re.match(r'^\d{1,5}$', line):
            continue
        if re.match(r'^\d{1,5}[,]\d{1,3}$', line):
            continue
        
        # === 언론사명/크레딧 ===
        if re.match(r'^OSEN$', line):
            continue
        if re.match(r'^OSEN\s+DB$', line):
            continue
        if re.match(r'^엔터플레이$', line):
            continue
        
        # === 프로그램/앵커 ===
        if re.match(r'^아침&\s*소셜픽$', line):
            continue
        if re.match(r'^[가-힣]{2,4}\s+앵커$', line):
            continue
        
        # === 링크 패턴 ===
        if re.match(r'^\(\/author\/\d+\)$', line):
            continue
        
        # === 네비게이션 블록 ===
        if re.match(r'^관련\s*키워드$', line):
            continue
        if re.match(r'^주요\s*기사$', line):
            continue
        
        # === 뉴스1 푸터 정보 ===
        if re.match(r'^대표이사\/발행인\s*[:：]', line):
            continue
        if re.match(r'^편집인\s*[:：]', line):
            continue
        if re.match(r'^편집국장\s*[:：]', line):
            continue
        if re.match(r'^주소\s*[:：]', line):
            continue
        if re.match(r'^사업자등록번호\s*[:：]', line):
            continue
        if re.match(r'^고충처리인\s*[:：]', line):
            continue
        if re.match(r'^청소년보호책임자\s*[:：]', line):
            continue
        if re.match(r'^통신판매업신고\s*[:：]', line):
            continue
        if re.match(r'^등록일\s*[:：]', line):
            continue
        if re.match(r'^제호\s*[:：]', line):
            continue
        if re.match(r'^대표\s*전화\s*[:：]', line):
            continue
        if re.match(r'^대표\s*이메일\s*[:：]', line):
            continue
        if re.search(r'뉴스1코리아\(읽기:', line):
            continue
        
        # === 저작권 (뉴스1 형식) ===
        if re.match(r'^Copyright\s*ⓒ\s*뉴스1\.', line, re.I):
            continue
        if re.search(r'무단\s*사용\s*및\s*재배포.*?금지', line, re.I):
            continue
        
        # === 조선일보 해시태그 단어 (# 없이) ===
        if re.match(r'^[a-zA-Z가-힣\s-]+$', line):
            keywords = ['케데헌', '케이팝\\s*데몬\\s*헌터스', 'kpopdemonhunters', '마텔', '해즈브로',
                       '크리스마스', '넷플릭스', '태평로', 'K-컬처', 'K팝', '짝퉁', 'Golden', 
                       'KATSEYE', '트와이스', 'Strategy', '루미', '미라', '조이', '헌트릭스', 
                       '제너럴\\s*필즈', '그래미', '아파트', '로제', '캣츠아이', '골든', 
                       '브루노\\s*마스', '찰스\\d+세', '사자보이즈', '이중정체성', 
                       '오드리\\s*누나', '레이\\s*아미', '김종은']
            should_skip = False
            for kw in keywords:
                if re.match(f'^{kw}$', line, re.I):
                    should_skip = True
                    break
            if should_skip:
                continue
        
        # === 날짜/시간 메타 정보 ===
        if re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+[가-힣]+$', line):
            continue
        if re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$', line):
            continue
        if re.match(r'^\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}$', line):
            continue
        if re.search(r'입력\s*\d{4}\.\d{2}\.\d{2}', line):
            continue
        if re.search(r'수정\s*\d{4}\.\d{2}\.\d{2}', line):
            continue
        if re.search(r'업데이트\s*\d{4}\.\d{2}\.\d{2}', line):
            continue
        
        # === 네비게이션 ===
        if re.match(r'^최신뉴스$', line):
            continue
        if re.match(r'^더보기$', line):
            continue
        if re.match(r'^다른기사보기$', line):
            continue
        if re.match(r'^돌아가기$', line):
            continue
        if re.match(r'^관련\s*기사$', line):
            continue
        
        # === UI 워딩 ===
        if re.search(r'바로가기|복사하기|본문 글씨', line):
            continue
        if re.match(r'^전체재생$', line):
            continue
        if re.match(r'^이전\s+다음$', line):
            continue
        if re.match(r'^좋아요$|^응원수$', line):
            continue
        if re.search(r'^동영상\s*고정', line):
            continue
        if re.match(r'^재생$|^일시정지$|^음소거$', line):
            continue
        if re.match(r'^현재위치$', line):
            continue
        if re.match(r'^인쇄$', line):
            continue
        
        # === 마크다운 헤더 ===
        if re.match(r'^#{1,6}\s', line):
            continue
        
        # === 기사 헤더 ===
        if re.match(r'^<\s*[가-힣]+\s*<\s*기사본문\s*-', line):
            continue
        if re.match(r'^기사검색\s*_검색_$', line):
            continue
        
        # === SNS 공유 ===
        if re.search(r'SNS 기사보내기', line):
            continue
        if re.search(r'페이스북\(으\)로 기사보내기', line):
            continue
        if re.search(r'트위터\(으\)로 기사보내기', line):
            continue
        if re.search(r'카카오스토리\(으\)로 기사보내기', line):
            continue
        if re.search(r'URL복사\(으\)로 기사보내기', line):
            continue
        if re.search(r'다른 공유 찾기|기사스크랩하기', line):
            continue
        
        # === 영역 표시 ===
        if re.match(r'^상단영역$', line):
            continue
        if re.match(r'^본문영역$', line):
            continue
        if re.match(r'^하단영역$', line):
            continue
        if re.match(r'^전체기사$', line):
            continue
        
        # === 로그인/회원 ===
        if re.match(r'^로그인$|^회원가입$|^모바일웹$', line):
            continue
        
        # === 광고/추천 콘텐츠 ===
        if re.search(r'By Taboola|Sponsored|Learn More', line):
            continue
        if re.search(r'당신이 좋아할|지금 뜨는|계속 읽어보세요', line):
            continue
        
        # === 기자 정보 ===
        if len(line) < 50:
            if re.match(r'^기자\s*[\/]?\s*$', line):
                continue
            if re.search(r'기자\s+구독', line):
                continue
            if re.search(r'기자\s*=$', line):
                continue
            if re.match(r'^[가-힣\s]{2,10}기자$', line):
                continue
            if re.search(r'\/기자$', line):
                continue
            if re.match(r'^[가-힣\s]+AI\s*리포터$', line):
                continue
            
            # 기자 이름 단독 라인
            if re.match(r'^[가-힣]{2,4}$', line):
                # 본문에 나올 수 있는 일반 단어는 제외
                common_words = ['하지만', '그러나', '또한', '따라서', '한편', '이날', '오늘',
                               '어제', '내일', '올해', '작년', '지난해', '최근', '당시', '이후',
                               '현재', '앞서', '특히', '이미', '다만', '다시', '여전히', '계속',
                               '이어', '먼저', '이번', '지난', '문화']
                if line not in common_words:
                    continue
            
            # 특파원/기자 패턴
            if re.match(r'^[가-힣]+\s*[=＝]\s*[가-힣\s]+\s*(특파원|기자)$', line):
                continue
        
        if re.match(r'^[가-힣]{2,4}\s*기자\s*\/\s*경제를 읽는', line):
            continue
        if re.search(r'\([^)]*=\s*연합뉴스\)', line):
            continue
        if re.search(r'조선NS 기자', line):
            continue
        
        # 이메일 단독 라인
        if re.match(r'^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', line):
            continue
        
        # === 경인신문 ===
        if re.match(r'^_기자명_\s*[가-힣]+\s*기자', line):
            continue
        if re.match(r'^\*+\s*입력\s*\d{4}', line):
            continue
        if re.match(r'^\*+\s*수정\s*\d{4}', line):
            continue
        if re.match(r'^\*+\s*댓글', line):
            continue
        
        # === 맥스무비 ===
        if re.match(r'^\[맥스무비=\s*[가-힣]+\s*기자\]$', line):
            continue
        if re.search(r'기자\s*\/\s*[a-zA-Z0-9._-]+@maxmovie\.com', line):
            continue
        if re.search(r'기사\s*제보\s*및\s*보도자료', line):
            continue
        if re.search(r'maxpress@maxmovie\.com', line):
            continue
        if re.match(r'^Now$|^리뷰&포테이토지수$|^시사회·이벤트$|^포토&영상$|^무비레터$|^매거진$', line):
            continue
        
        # 맥스무비 추가 패턴
        if re.match(r'^\d+분\s*이내$', line):
            continue
        if re.match(r'^글자\s*크기\s*변경$', line):
            continue
        if re.match(r'^이\s*기사를\s*추천합니다\.?$', line):
            continue
        if re.match(r'^입력\s*\d{4}\.\d{2}\.\d{2}', line):
            continue
        if re.match(r'^외$', line):
            continue
        if re.match(r'^명$', line):
            continue
        if re.match(r'^댓글보기$', line):
            continue
        if re.match(r'^공유하기$', line):
            continue
        if re.match(r'^스크랩$', line):
            continue
        if re.match(r'^인쇄하기$', line):
            continue
        
        # === 기자 프로필 ===
        if re.search(r'특파원\.|기자입니다\.|다룹니다\.|씁니다\.|맡고 있습니다\.', line):
            continue
        if re.search(r'을\/를 다룹니다\.|을\/를 씁니다\.', line):
            continue
        
        # === 댓글 ===
        if re.match(r'^댓글\s*\d+$', line):
            continue
        if re.match(r'^댓글을\s*입력해주세요$', line):
            continue
        if re.match(r'^등록$', line):
            continue
        if re.match(r'^0\/\s*\d+$', line):
            continue
        if re.match(r'^100자평$', line):
            continue
        if re.match(r'^도움말$|^삭제기준$', line):
            continue
        if re.match(r'^최신순$|^관심순$', line):
            continue
        
        # === 사진 설명 ===
        if re.match(r'^[▲▼]\s*사진\s*=', line):
            continue
        if re.match(r'^[▲▼]\s*출처\s*[:：=]', line):
            continue
        if re.match(r'^\/사진\s*=\s*[가-힣]+\s*기자$', line):
            continue
        if re.match(r'^\/\s*사진\s*제공\s*=', line):
            continue
        if re.match(r'^사진제공\s*[=:]', line):
            continue
        if re.match(r'^\([가-힣\s]+\s*제공\)$', line):
            continue
        if re.match(r'^\([가-힣\s]+(제공|DB)\)$', line):
            continue
        if re.match(r'^Netflix$', line):
            continue
        if re.match(r'^포토\s+Netflix$', line):
            continue
        
        # === 링크 ===
        if re.match(r'^\[\]$', line):
            continue
        if re.match(r'^\[\]\(\)$', line):
            continue
        if re.match(r'^\[\]\(mailto:', line):
            continue
        if re.match(r'^mailto:', line):
            continue
        if re.match(r'^\[•', line):
            continue
        
        # === 구분선 ===
        if re.match(r'^---+$', line):
            continue
        if re.match(r'^===+$', line):
            continue
        if re.match(r'^={10,}$', line):
            continue
        
        # === 저작권 ===
        if re.match(r'^<저작권자\(c\)', line):
            continue
        if re.search(r'무단전재\s*및\s*재배포\s*금지', line):
            continue
        if re.search(r'저작권자\s*©', line):
            continue
        if re.search(r'저작권자|무단|전재|재배포|금지', line):
            continue
        if re.search(r'제보하기', line):
            continue
        if '▷' in line:
            continue
        if line.startswith('■'):
            continue
        
        # === 기타 ===
        if re.match(r'^출처\s*[:：]', line):
            continue
        if line.startswith('📸'):
            continue
        if re.match(r'^###\s*\d+$', line):
            continue
        if re.match(r'^###\s', line):
            continue
        
        # === 표/구조 ===
        if re.match(r'^구분\s+내용$', line):
            continue
        if re.match(r'^작품명|^제작|^공개 예정|^전편 공개|^특징|^흥행|^연출|^핵심 주제|^기대 포인트', line):
            continue
        
        # === 후원 안내 ===
        if re.search(r'후원금을 귀하게 쓰겠습니다', line):
            continue
        
        filtered_lines.append(line)
    
    # 11단계: 후처리
    txt = '\n'.join(filtered_lines)
    txt = re.sub(r'!\[.*?\]\(.*?\)', '', txt)
    txt = re.sub(r'\[[^\]]+\]\(mailto:[^\)]+\)', '', txt)
    txt = re.sub(r'\[[^\]]+\]\([^\)]+\)', '', txt)
    txt = re.sub(r'https?:\/\/[^\s)]+', '', txt)
    txt = re.sub(r'mailto:[^\s]+', '', txt)
    txt = re.sub(r'[▶▷●◆■★※▲▼→←↑↓#]', '', txt)
    txt = re.sub(r'[|│]+', '', txt)
    txt = re.sub(r'\*\*', '', txt)
    txt = re.sub(r'\[\]', '', txt)
    txt = re.sub(r'\n{2,}', '\n\n', txt)
    txt = re.sub(r' {2,}', ' ', txt)
    txt = re.sub(r'\[\]\(\)', '', txt)
    
    # 마크다운 리스트 제거 (끝부분 + 중간 빈 리스트)
    txt = re.sub(r'\n\n(\*\s*\n)+$', '', txt)
    txt = re.sub(r'\n\n\*\s*\n\*', '\n', txt)
    txt = re.sub(r'(\n\*\s*){3,}', '\n', txt)
    
    txt = txt.strip()
    
    # 12단계: 최종 기자 정보 제거
    txt = re.sub(r'\([^)]*기자\)\s*', '', txt)
    txt = re.sub(r'\n*사진\s*[=:：]\s*[^\n]*기자\s*$', '', txt)
    txt = re.sub(r'\n*영상\s*[=:：]\s*[^\n]*기자\s*$', '', txt)
    txt = re.sub(r'\n*그래픽\s*[=:：]\s*[^\n]*기자\s*$', '', txt)
    txt = re.sub(r'\n*[가-힣]{2,4}\s*기자\s*[a-zA-Z0-9._-]+@[^\s]+\s*$', '', txt)
    txt = re.sub(r'\n*[가-힣]{2,4}\s*기자\s*\/\s*경제를 읽는[^\n]*$', '', txt)
    
    # iMBC연예 패턴 제거
    txt = re.sub(r'\n+iMBC연예\s*[가-힣]+\s*$', '', txt)
    txt = re.sub(r'\niMBC연예\s*[가-힣]+$', '', txt)
    
    txt = txt.strip()
    return txt

app = FastAPI(
    title="News Extractor API (Dynamic)",
    description="Playwright 기반 동적 렌더링 뉴스 본문 추출 API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 예외 핸들러
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 검증 에러를 일관된 형식으로 변환"""
    error_messages = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error.get("loc", []))
        msg = error.get("msg", "Validation error")
        error_messages.append(f"{field}: {msg}")
    
    error_text = "; ".join(error_messages) if error_messages else "요청 형식이 올바르지 않습니다."
    
    # 요청에서 URL 추출 시도
    body_bytes = getattr(exc, 'body', None)
    url_str = await extract_url_from_request(request, body_bytes)
    
    return JSONResponse(
        status_code=200,
        content={
            "success": False,
            "url": url_str,
            "content": "",
            "content_length": 0,
            "extraction_method": "playwright-stealth",
            "error": f"요청 검증 실패: {error_text}"
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """모든 예외를 일관된 형식으로 반환"""
    url_str = await extract_url_from_request(request)
    
    return JSONResponse(
        status_code=200,
        content={
            "success": False,
            "url": url_str,
            "content": "",
            "content_length": 0,
            "extraction_method": "playwright-stealth",
            "error": f"서버 오류: {str(exc)}"
        }
    )

class ExtractRequest(BaseModel):
    url: HttpUrl

class ExtractResponse(BaseModel):
    success: bool
    url: str
    content: str
    content_length: int
    extraction_method: str
    error: Optional[str] = None


async def extract_url_from_request(request: Request, body_bytes: bytes = None) -> str:
    """
    요청에서 URL을 추출 시도
    Returns: url_str
    """
    if body_bytes:
        body_text = None
        try:
            body_text = body_bytes.decode('utf-8')
            body = json.loads(body_text)
            if isinstance(body, dict) and "url" in body:
                return str(body["url"])
        except:
            pass
        
        if body_text:
            try:
                url_match = re.search(r'https?://[^\s"\'<>]+', body_text)
                if url_match:
                    return url_match.group(0)
            except:
                pass
    
    try:
        body = await request.json()
        if isinstance(body, dict) and "url" in body:
            return str(body["url"])
    except:
        pass
    
    return ""


async def extract_with_playwright(url: str) -> dict:
    """
    Playwright Stealth 모드로 동적 렌더링 사이트 추출
    
    Vogue 전략 적용:
    - Stealth 모드로 봇 감지 우회
    - domcontentloaded까지만 빠르게 로드
    - 최소한의 안정화 대기 (2초)
    - clean_news_body()로 메타데이터 제거
    """
    try:
        async with async_playwright() as p:
            # 브라우저 실행 (Stealth 모드 최적화)
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--single-process',
                    '--disable-blink-features=AutomationControlled',  # 자동화 감지 차단
                ]
            )
            
            # Context 생성 (viewport, user-agent 설정)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            page = await context.new_page()
            
            # Stealth 모드 적용
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
            
            # 리소스 차단 (이미지, 폰트, CSS)
            await page.route("**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf}", lambda route: route.abort())
            
            # 페이지 로드 (domcontentloaded만 대기, 타임아웃 15초)
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                print(f"✅ 페이지 로드 완료: {url}")
                
                # 즉시 HTML 추출
                html = await page.content()
                print(f"✅ HTML 추출 성공! 길이: {len(html):,}자")
                
                # 짧은 안정화 대기 (2초)
                print("⏳ 짧은 안정화 대기 (2초)...")
                await page.wait_for_timeout(2000)
                
                # 최종 HTML 가져오기
                html = await page.content()
                print(f"✅ 최종 HTML 길이: {len(html):,}자")
                
            except PlaywrightTimeoutError:
                print("⚠️ 타임아웃, 현재 HTML로 진행...")
                html = await page.content()
            
            # 브라우저 닫기
            await context.close()
            await browser.close()
            
            # BeautifulSoup으로 본문 추출
            soup = BeautifulSoup(html, 'html.parser')
            
            # script, style, 네비게이션 요소 제거
            for script in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
                script.decompose()
            
            # 광고, 관련기사 등 불필요한 요소 제거
            for element in soup.find_all(class_=re.compile(r'ad|advertisement|banner|sidebar|related|comment|share|social', re.I)):
                element.decompose()
            
            # 본문 추출 전략 (Vogue 전략)
            content = ""
            
            # 전략 1: article 태그에서 p 태그 추출 (30자 이상만)
            article = soup.find('article')
            if article:
                paragraphs = article.find_all('p')
                texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
                content = '\n\n'.join(texts)
            
            # 전략 2: class 기반 검색
            if len(content) < 100:
                for selector in ['.article-content', '.post-content', '.entry-content', '.content', 
                                '.article_body', '.article-body', '.post_content', '.story-body']:
                    element = soup.select_one(selector)
                    if element:
                        paragraphs = element.find_all('p')
                        texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
                        content = '\n\n'.join(texts)
                        if len(content) > 100:
                            break
            
            # 전략 3: main 태그
            if len(content) < 100:
                main = soup.find('main')
                if main:
                    paragraphs = main.find_all('p')
                    texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
                    content = '\n\n'.join(texts)
            
            # 전략 4: body 전체에서 p 태그 검색
            if len(content) < 100:
                paragraphs = soup.find_all('p')
                texts = []
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if len(text) > 30:
                        # 광고/네비/메타데이터 제외
                        if not any(keyword in text.lower() for keyword in ['쿠키', 'cookie', '로그인', 'login', '구독', 'subscribe']):
                            texts.append(text)
                content = '\n\n'.join(texts)
            
            content_stripped = content.strip()
            content_length = len(content_stripped)
            
            # 100자 이하면 실패
            if content_length < 100:
                return {
                    "success": False,
                    "url": url,
                    "content": content_stripped,
                    "content_length": content_length,
                    "extraction_method": "playwright-stealth",
                    "error": f"본문이 너무 짧습니다 ({content_length}자). Playwright로도 충분한 내용을 추출하지 못했습니다."
                }
            
            # 본문 정제
            content_cleaned = clean_news_body(content_stripped)
            content_length_cleaned = len(content_cleaned)
            
            return {
                "success": True,
                "url": url,
                "content": content_cleaned,
                "content_length": content_length_cleaned,
                "extraction_method": "playwright-stealth",
                "error": None
            }
                
    except PlaywrightTimeoutError:
        return {
            "success": False,
            "url": url,
            "content": "",
            "content_length": 0,
            "extraction_method": "playwright-stealth",
            "error": "페이지 로드 타임아웃 (30초 초과, 하지만 부분 로딩 시도함)"
        }
    except Exception as e:
        return {
            "success": False,
            "url": url,
            "content": "",
            "content_length": 0,
            "extraction_method": "playwright-stealth",
            "error": f"Playwright 추출 실패: {str(e)}"
        }


@app.get("/")
def root():
    """API 정보"""
    return {
        "service": "News Extractor API (Playwright Stealth)",
        "version": "3.0.0",
        "description": "Playwright Stealth 모드 뉴스 본문 추출 + 자동 메타데이터 제거",
        "method": "playwright-stealth",
        "quality_threshold": "본문 100자 이상",
        "performance": {
            "speed": "5-15초/기사",
            "use_case": "조선일보, imbc, Vogue, News1 등 까다로운 사이트"
        },
        "features": {
            "stealth_mode": "봇 감지 우회",
            "fast_extraction": "domcontentloaded 전략",
            "auto_cleanup": "메타데이터/기자정보/UI요소 자동 제거"
        },
        "endpoints": {
            "POST /playwright": "Playwright Stealth 추출",
            "GET /health": "헬스체크"
        },
        "notes": "Vogue 전략 적용. 빠르고 깨끗한 본문 추출."
    }


@app.get("/health")
def health_check():
    """헬스체크"""
    return {
        "status": "healthy",
        "service": "news-playwright-stealth-api",
        "method": "playwright-stealth",
        "version": "3.0.0"
    }


@app.post("/playwright")
async def extract_playwright(request: ExtractRequest):
    """
    Playwright Stealth 모드 뉴스 본문 추출
    
    - **url**: 추출할 뉴스 URL
    
    Returns:
    - success: 성공 여부 (본문 100자 이상이면 True)
    - url: 요청한 URL
    - content: 기사 본문 (메타데이터 자동 제거)
    - content_length: 본문 길이
    - extraction_method: "playwright-stealth"
    - error: 에러 메시지 (실패 시)
    
    Note:
    - Playwright Stealth 모드로 봇 감지 우회
    - domcontentloaded 전략으로 빠른 추출
    - clean_news_body()로 자동 필터링
    - 처리 시간: 5-15초/기사
    - 모든 응답은 HTTP 200으로 반환됩니다
    """
    try:
        url_str = str(request.url) if request.url else ""
        if not url_str:
            raise ValueError("URL이 제공되지 않았습니다.")
        
        # Playwright Stealth 모드 실행
        result = await extract_with_playwright(url_str)
        
        return JSONResponse(
            status_code=200,
            content=result
        )
        
    except Exception as e:
        try:
            url_str = str(request.url) if request.url else ""
        except:
            url_str = ""
        
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "url": url_str,
                "content": "",
                "content_length": 0,
                "extraction_method": "playwright-stealth",
                "error": f"서버 내부 오류: {str(e)}"
            }
        )


if __name__ == "__main__":
    # 기본 포트 8001 사용 (8000과 구분)
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)