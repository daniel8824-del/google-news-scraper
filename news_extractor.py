# newspaper3k 기반 뉴스 추출 API (v2.3)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, HttpUrl
from typing import Optional
from newspaper import Article
import json
import re
import uvicorn

app = FastAPI(
    title="News Extractor API",
    description="newspaper3k 기반 뉴스 본문 추출 API (본문 자동 정제 기능 포함)",
    version="2.3.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 예외 핸들러: 모든 에러를 일관된 형식으로 반환
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
        status_code=200,  # HTTP 200으로 반환 (워크플로우 중단 방지)
        content={
            "success": False,
            "url": url_str,
            "content": "",
            "content_length": 0,
            "extraction_method": "newspaper3k",
            "error": f"요청 검증 실패: {error_text}"
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """모든 예외를 일관된 형식으로 반환"""
    # 요청에서 URL 추출 시도
    url_str = await extract_url_from_request(request)
    
    return JSONResponse(
        status_code=200,  # HTTP 200으로 반환 (워크플로우 중단 방지)
        content={
            "success": False,
            "url": url_str,
            "content": "",
            "content_length": 0,
            "extraction_method": "newspaper3k",
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
    # body_bytes가 제공된 경우 사용 (RequestValidationError에서)
    if body_bytes:
        body_text = None
        try:
            body_text = body_bytes.decode('utf-8')
            # JSON 파싱 시도
            body = json.loads(body_text)
            if isinstance(body, dict) and "url" in body:
                return str(body["url"])
        except:
            pass
        
        # JSON 파싱 실패 시 텍스트에서 URL 패턴 찾기
        if body_text:
            try:
                url_match = re.search(r'https?://[^\s"\'<>]+', body_text)
                if url_match:
                    return url_match.group(0)
            except:
                pass
    
    # body_bytes가 없는 경우 요청 본문 읽기 시도
    try:
        body = await request.json()
        if isinstance(body, dict) and "url" in body:
            return str(body["url"])
    except:
        pass
    
    return ""


def clean_news_body(raw_content: str) -> str:
    """
    뉴스 본문에서 불필요한 메타데이터, 기자 정보, UI 요소 등을 제거
    
    JavaScript cleanNewsBody 함수의 Python 버전
    """
    if not raw_content:
        return raw_content
    
    if not isinstance(raw_content, str):
        return raw_content
    
    if len(raw_content) < 50:
        return raw_content
    
    # ═══════════════════════════════════════════════════════
    # STEP 1: 블로그 헤더 제거
    # ═══════════════════════════════════════════════════════
    is_blog = bool(re.search(r'루빵루나|URL 복사|본문 기타 기능', raw_content))
    has_share_pattern = bool(re.search(r'공유하기\s*신고하기', raw_content))
    
    if is_blog and has_share_pattern:
        share_match = re.search(r'공유하기\s*신고하기', raw_content)
        if share_match:
            share_index = share_match.start()
            if share_index > 0 and share_index < len(raw_content) * 0.3:
                raw_content = re.sub(r'^[\s\S]*?공유하기\s*신고하기\s*', '', raw_content)
    
    # ═══════════════════════════════════════════════════════
    # STEP 2: 기자 정보 제거
    # ═══════════════════════════════════════════════════════
    
    # /기자명 이메일 패턴 제거 (/ 포함)
    raw_content = re.sub(r'\n\/[가-힣]{2,4}\s*기자\s*[a-zA-Z0-9._-]+@[^\s\n]+', '', raw_content)
    raw_content = re.sub(r'\/[가-힣]{2,4}\s*기자\s*[a-zA-Z0-9._-]+@[^\s\n]+', '', raw_content)
    
    # /지역명 기자명 이메일 패턴 제거 (/ 포함)
    raw_content = re.sub(r'\n\/[가-힣]+\s*[가-힣]{2,4}기자\s*[a-zA-Z0-9._-]+@[^\s\n]+', '', raw_content)
    raw_content = re.sub(r'\/[가-힣]+\s*[가-힣]{2,4}기자\s*[a-zA-Z0-9._-]+@[^\s\n]+', '', raw_content)
    raw_content = re.sub(r'\[디지털데일리\s*[가-힣]+기자\]', '', raw_content)
    raw_content = re.sub(r'\[디지털투데이\s*AI\s*리포터\]', '', raw_content)
    raw_content = re.sub(r'\[[가-힣]+(?:데일리|투데이|뉴스|타임즈)\s*[가-힣]*(?:기자|리포터|AI리포터)\]', '', raw_content)
    
    # 기본 기자 패턴
    raw_content = re.sub(r'\([\s가-힣]*=\s*연합뉴스\)\s*[가-힣\s]+기자\s*[=]*\s*', '', raw_content)
    raw_content = re.sub(r'\([^)]*=\s*[^)]+\)\s*[가-힣\s]+기자\s*[=]*\s*', '', raw_content)
    raw_content = re.sub(r'[가-힣]+기자\s+구독\s+구독중', '', raw_content)
    raw_content = re.sub(r'\[[^\]]*기자\]', '', raw_content)
    
    # 언론사=기자 패턴
    raw_content = re.sub(r'브레이크뉴스\s+[가-힣]{2,4}\s*기자\s*=\s*', '', raw_content)
    
    # 언론사 구분자
    raw_content = re.sub(r'\n리걸타임즈\s*$', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'리걸타임즈\s+[가-힣]{2,4}\s*기자', '', raw_content)
    
    # 중앙이코노미뉴스 패턴
    raw_content = re.sub(r'\[중앙이코노미뉴스\s+[가-힣]{2,4}\]', '', raw_content)
    
    # iMBC연예 패턴
    raw_content = re.sub(r'iMBC연예\s+[가-힣]{2,4}\s*\|\s*사진출처[^\n]*', '', raw_content)
    raw_content = re.sub(r'iMBC연예\s+[가-힣]{2,4}', '', raw_content)
    
    # 빈 괄호 기자 정보
    raw_content = re.sub(r'[가-힣]{2,4}\s*기자\s*\(\s*\)', '', raw_content)
    raw_content = re.sub(r'\n[가-힣]{2,4}\s*기자\s*\(\s*\)\s*$', '', raw_content, flags=re.MULTILINE)
    
    # 언론사 구분자 패턴
    raw_content = re.sub(r'[가-힣]+타임스\s*=\s*[가-힣]{2,4}\s*기자\s*\|', '', raw_content)
    raw_content = re.sub(r'\n문화뉴스\s*\/\s*$', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'문화뉴스\s*\/\s*', '', raw_content)
    
    # 방송 언론사 패턴
    raw_content = re.sub(r'\n[가-힣]{2,4}\s*머니투데이방송\s*MTN\s*기자\s*$', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'[가-힣]{2,4}\s*머니투데이방송\s*MTN\s*기자', '', raw_content)
    
    # AI리포터 패턴
    raw_content = re.sub(r'\[[^\]]*AI\s*리포터\]', '', raw_content)
    raw_content = re.sub(r'\[[가-힣]+(?:데일리|투데이|뉴스|타임즈|경제|일보|신문)\s+[가-힣]+(?:기자|리포터)\]', '', raw_content)
    raw_content = re.sub(r'\[[가-힣]+(?:데일리|투데이|뉴스|타임즈|경제|일보|신문)\s+AI\s*리포터\]', '', raw_content)
    raw_content = re.sub(r'\[[가-힣]+\s+[가-힣]{2,4}기자\]', '', raw_content)
    
    # 뉴스1 특수 패턴
    raw_content = re.sub(r'\([가-힣]+=뉴스1\)\s*=\s*', '', raw_content)
    raw_content = re.sub(r'\([^)]*제공\.\s*재판매\s*및\s*DB\s*금지\)\s*\d{4}\.\d{1,2}\.\d{1,2}\/뉴스1', '', raw_content)
    
    # 뉴시스 패턴
    raw_content = re.sub(r'ⓒ뉴시스', '', raw_content)
    raw_content = re.sub(r'\[([가-힣]+)=뉴시스\]\s*', '', raw_content)
    raw_content = re.sub(r'\[([가-힣]+)=뉴시스\][가-힣\s]+기자\s*=\s*', '', raw_content)
    raw_content = re.sub(r'[a-zA-Z0-9._-]+@newsis\.com', '', raw_content)
    
    raw_content = re.sub(r'^[가-힣]{2,4}\s+기자\s*=\s*', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'\n[가-힣]{2,4}\s+기자\s*=\s*', '', raw_content)
    
    # BBC 스타일 기자 정보
    raw_content = re.sub(r'^기자,\s*[^\n]+기자,?\s*[^\n]*$', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'기자,\s*[가-힣\s]+기자', '', raw_content)
    
    # 내외경제TV 패턴
    raw_content = re.sub(r'\|\s*[^\|]+=[가-힣\s]+기자\s*\|\s*=\s*', '', raw_content)
    
    # 내외뉴스통신 패턴
    raw_content = re.sub(r'\[[^\]]+\]\s*[가-힣\s]+기자', '', raw_content)
    raw_content = re.sub(r'\|\s*[^\|]+=[가-힣\s]+기자\s*\|', '', raw_content)
    
    # 도시/통신사 연합뉴스 패턴
    raw_content = re.sub(r'[가-힣]+\/(로이터|AFP|AP|블룸버그|Getty Images)\s+연합뉴스', '', raw_content)
    raw_content = re.sub(r'^[가-힣]+\/(로이터|AFP|AP|블룸버그|Getty Images)\s+연합뉴스\s*$', '', raw_content, flags=re.MULTILINE)
    
    # 특파원 뒤 viewer 제거
    raw_content = re.sub(r'([가-힣]+=?[가-힣\s]+특파원)\s*\n\s*viewer\s*', r'\1', raw_content, flags=re.IGNORECASE)
    
    # 도시=특파원 패턴 제거
    raw_content = re.sub(r'[가-힣]+=[가-힣]{2,4}\s*특파원', '', raw_content)
    raw_content = re.sub(r'^[가-힣]+=[가-힣]{2,4}\s*특파원\s*$', '', raw_content, flags=re.MULTILINE)
    
    # ═══════════════════════════════════════════════════════
    # STEP 3: 연합뉴스 태그 제거
    # ═══════════════════════════════════════════════════════
    raw_content = re.sub(r'<연합뉴스>', '', raw_content)
    raw_content = re.sub(r'^<연합뉴스>\s*$', '', raw_content, flags=re.MULTILINE)
    
    # / 연합뉴스 패턴
    raw_content = re.sub(r'\/\s*연합뉴스\s*', '', raw_content)
    raw_content = re.sub(r'\n\/\s*연합뉴스\s*$', '', raw_content, flags=re.MULTILINE)
    
    # ═══════════════════════════════════════════════════════
    # STEP 4: TTS 오디오 플레이어 제거
    # ═══════════════════════════════════════════════════════
    raw_content = re.sub(r'기사를\s*읽어드립니다\s*Your\s*browser\s*does\s*not\s*support\s*the\s*audio\s*element\.\s*\d+:\d+\s*', '', raw_content)
    
    # ═══════════════════════════════════════════════════════
    # STEP 5: 사진/영상 메타 정보 제거
    # ═══════════════════════════════════════════════════════
    
    # 출처 괄호 패턴
    raw_content = re.sub(r'\(화면출처\s*[:：]?\s*[^\)]+\)', '', raw_content)
    raw_content = re.sub(r'\(사진\s*=\s*[^\)]+\s*제공\)', '', raw_content)
    raw_content = re.sub(r'\(사진출처=[^\)]+\)', '', raw_content)
    raw_content = re.sub(r'\(출처=[^\)]+\)', '', raw_content)
    
    # 사진='...' 유튜브 캡처
    raw_content = re.sub(r'\(사진=[\'"][^\'"]+[\'\"]\s*유튜브\s*캡처,\s*연합뉴스\)', '', raw_content)
    
    # 사진 출처 패턴
    raw_content = re.sub(r'<사진출처=[^>]+>', '', raw_content)
    raw_content = re.sub(r'\n<사진출처=[^>]+>\s*$', '', raw_content, flags=re.MULTILINE)
    
    # iMBC 사진출처
    raw_content = re.sub(r'\/\s*사진출처\s*[^\n]+\/\s*※이 기사의 저작권은 iMBC[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\/\s*사진출처\s*[^\n]+\s*\/\s*', '', raw_content, flags=re.IGNORECASE)
    
    # SNS 캡처
    raw_content = re.sub(r'SNS\s*캡처', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\nSNS\s*캡처\s*$', '', raw_content, flags=re.MULTILINE | re.IGNORECASE)
    
    # 게티이미지
    raw_content = re.sub(r'사진\s*\/\s*gettyimagesBank', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\n사진\s*\/\s*gettyimagesBank\s*$', '', raw_content, flags=re.MULTILINE | re.IGNORECASE)
    
    # 큰사진보기 이미지 메타데이터
    raw_content = re.sub(r'큰사진보기\s*▲[^\n]*ⓒ[^\n]*관련사진보기', '', raw_content, flags=re.IGNORECASE)
    
    # 사진 확대
    raw_content = re.sub(r'사진\s*확대', '', raw_content, flags=re.IGNORECASE)
    
    # 사진 크레딧
    raw_content = re.sub(r'\/사진\s*=\s*[가-힣]+\s*기자', '', raw_content)
    raw_content = re.sub(r'\/\s*사진\s*제공\s*=\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'[▲▼][^\n]*(?:\/사진=|©)[^\n]*', '', raw_content)
    raw_content = re.sub(r'[▲▼]\s*사진\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'[▲▼]\s*출처\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'사진\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'사진제공\s*[:：=]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'사진제공\s*[｜|]\s*[^\n]+', '', raw_content)
    raw_content = re.sub(r'^사진제공\s*[｜|]\s*[^\n]+$', '', raw_content, flags=re.MULTILINE)
    
    # 뉴스1 사진 패턴
    raw_content = re.sub(r'\d{4}\.\d{1,2}\.\d{1,2}\/뉴스1\s*ⓒ\s*News1', '', raw_content)
    
    # BBC 스타일 사진 메타
    raw_content = re.sub(r'^사진\s*출처,\s*[^\n]+$', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'^사진\s*설명,\s*[^\n]+$', '', raw_content, flags=re.MULTILINE)
    
    # 미디어 태그
    raw_content = re.sub(r'\[사진[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[영상[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[이미지[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[동영상[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\[그래픽[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\n?\[사진[^\]]*\]', '', raw_content)
    raw_content = re.sub(r'\n?사진[:：]\s*[^\n]+\]', '', raw_content)
    
    # 재판매 및 DB 금지 패턴
    raw_content = re.sub(r'[^\n]*\[[^\]]*(?:제공|연합뉴스|캡처|자료사진)\.\s*재판매\s*및\s*DB\s*금지\]', '', raw_content)
    raw_content = re.sub(r'\*재판매\s*및\s*DB\s*금지', '', raw_content)
    
    # ═══════════════════════════════════════════════════════
    # STEP 6: 방송 대본/인터뷰 패턴 제거
    # ═══════════════════════════════════════════════════════
    raw_content = re.sub(r'◀\s*(앵커|리포트|기자|인터뷰)\s*▶', '\n', raw_content)
    raw_content = re.sub(r'\[[^\]]+\/[^\]]+\s*\([^)]+\)\]', '', raw_content)
    
    # ═══════════════════════════════════════════════════════
    # STEP 7: 영상 제작 정보 제거
    # ═══════════════════════════════════════════════════════
    raw_content = re.sub(r'영상취재\s*[:：][^\n▷]*', '', raw_content)
    raw_content = re.sub(r'영상편집\s*[:：][^\n▷]*', '', raw_content)
    raw_content = re.sub(r'영상제공\s*[:：][^\n▷]*', '', raw_content)
    raw_content = re.sub(r'MBC뉴스\s+[가-힣]+입니다\.', '', raw_content)
    
    # VOD 시청 안내
    raw_content = re.sub(r'VOD\s*시청\s*안내[\s\S]*?브라우저\s*업그레이드\s*및\s*설치\s*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'어도비\s*플래시\s*플레이어\s*서비스\s*종료[\s\S]*?브라우저\s*업그레이드[^\n]*', '', raw_content, flags=re.IGNORECASE)
    
    # 브라우저 지원 메시지
    raw_content = re.sub(r'브라우저가\s*(video|오디오)\s*태그를\s*지원하지\s*않습니다[\s\S]*?닫기\s*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'죄송하지만\s*다른\s*브라우저를\s*사용하여\s*주십시오\.', '', raw_content, flags=re.IGNORECASE)
    
    # YTN 영상 제작진 정보 블록
    raw_content = re.sub(r'\n영상기자\s*[:：]\s*[^\n]+\n영상편집\s*[;；:：]\s*[^\n]+[\s\S]*?YTN[^\n]*\n※\s*\'당신의 제보가 뉴스가 됩니다\'[\s\S]*?(\[메일\]|\[이메일\])[^\n]*', '', raw_content, flags=re.IGNORECASE)
    
    # YTN 제보 안내
    raw_content = re.sub(r'※\s*\'당신의 제보가 뉴스가 됩니다\'[\s\S]*?(\[메일\]|\[이메일\])[^\n]*', '', raw_content, flags=re.IGNORECASE)
    
    # YTN 관련 추가 패턴
    raw_content = re.sub(r'\[카카오톡\]\s*YTN\s*검색해\s*채널\s*추가', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\[전화\]\s*\d{2,3}-\d{3,4}-\d{4}', '', raw_content)
    
    # ═══════════════════════════════════════════════════════
    # STEP 8: 제보/연락처 정보 제거
    # ═══════════════════════════════════════════════════════
    raw_content = re.sub(r'▷\s*전화[^\n▷]*', '', raw_content)
    raw_content = re.sub(r'▷\s*이메일[^\n▷]*', '', raw_content)
    raw_content = re.sub(r'▷\s*카카오톡[^\n▷]*', '', raw_content)
    raw_content = re.sub(r'■\s*제보하기', '', raw_content)
    raw_content = re.sub(r'[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '', raw_content)
    
    # 연합뉴스TV 제보
    raw_content = re.sub(r'연합뉴스TV\s*기사문의\s*및\s*제보[\s\S]*?라인\s*앱에서[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'당신이\s*담은\s*순간이\s*뉴스입니다!', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'jebo23', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\n카톡\/라인\s*jebo23\s*', '', raw_content, flags=re.IGNORECASE)
    
    # 라인 앱 친구 추가
    raw_content = re.sub(r'\n라인\s*앱에서\s*[\'\']\s*친구\s*추가\s*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'라인\s*앱에서\s*[\'\']\s*친구\s*추가', '', raw_content, flags=re.IGNORECASE)
    
    # 제보 카카오톡 패턴
    raw_content = re.sub(r'\n제보는\s*카카오톡\s+[a-zA-Z0-9]+', '', raw_content)
    raw_content = re.sub(r'제보는\s*카카오톡\s+[a-zA-Z0-9]+', '', raw_content)
    
    # ═══════════════════════════════════════════════════════
    # STEP 9: UI 요소 제거
    # ═══════════════════════════════════════════════════════
    raw_content = re.sub(r'이미지\s*확대', '', raw_content)
    raw_content = re.sub(r'이전\s+다음', '', raw_content)
    raw_content = re.sub(r'좋아요\s*응원수', '', raw_content)
    raw_content = re.sub(r'viewer', '', raw_content, flags=re.IGNORECASE)
    
    # 글자크기 변경 안내
    raw_content = re.sub(r'기사의\s*본문\s*내용은\s*이\s*글자크기로\s*변경됩니다\.', '', raw_content)
    raw_content = re.sub(r'\n기사의\s*본문\s*내용은\s*이\s*글자크기로\s*변경됩니다\.\s*', '', raw_content)
    
    # AI 요약 안내
    raw_content = re.sub(r'AI\s*요약은\s*OpenAI의\s*최신\s*기술을[\s\S]*?함께\s*확인하는\s*것이\s*좋습니다\.', '', raw_content, flags=re.IGNORECASE)
    
    # Credits 패턴
    raw_content = re.sub(r'\nCredits\s+[^\n]+$', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'Credits\s+[A-Za-z\s]+', '', raw_content)
    
    # 기사의 이해를 돕기 위한 자료
    raw_content = re.sub(r'\n기사의\s*이해를\s*돕기\s*위한\s*자료\s*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'기사의\s*이해를\s*돕기\s*위한\s*자료\s*', '', raw_content, flags=re.IGNORECASE)
    
    # ═══════════════════════════════════════════════════════
    # STEP 10: 특수 패턴 제거
    # ═══════════════════════════════════════════════════════
    
    # 인포맥스 단말기 안내
    raw_content = re.sub(r'\n본 기사는 인포맥스 금융정보 단말기에서 \d{1,2}시 \d{1,2}분에 서비스된 기사입니다\.', '', raw_content)
    
    # 연합인포맥스/연합뉴스 특파원
    raw_content = re.sub(r'\n?\([가-힣]+=연합(인포맥스|뉴스)[^\)]*\)\s*[가-힣\s]+\s*(특파원|기자)\s*=\s*', '', raw_content)
    
    # 광고 표시
    raw_content = re.sub(r'\n광고\n', '\n', raw_content)
    raw_content = re.sub(r'^광고$', '', raw_content, flags=re.MULTILINE)
    
    # 괄호 안 기자 정보
    raw_content = re.sub(r'\(\n?\s*[가-힣\s]+기자\s*=\s*[^\)]*\)?', '', raw_content)
    raw_content = re.sub(r'\(\n?\s*[가-힣\s]+특파원\s*=\s*[^\)]*\)?', '', raw_content)
    
    # Grammy/시상식 대규모 리스트
    raw_content = re.sub(r'\n\d{4}\s+Grammy\s+nominees[\s\S]*?(?=\n\n[가-힣]|$)', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\n\*\s*(Record|Album|Song|Best)\s+of\s+the\s+Year[\s\S]*?(?=\n\n[가-힣]|$)', '', raw_content, flags=re.IGNORECASE)
    
    # 영문 기사 Google Translate 안내
    raw_content = re.sub(r'\n\*아래는\s*위\s*기사를\s*\'구글\s*번역\'으로\s*번역한\s*영문\s*기사의\s*\[전문\]입니다\.[\s\S]*?Hanteo Chart website\.', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'<\*The following is \[the full text\][\s\S]*?Google Translate\' is working hard to improve understanding[\s\S]*?>\s*', '', raw_content, flags=re.IGNORECASE)
    
    # 써클차트 데이터 블록
    raw_content = re.sub(r'\n함께\s*공개된\s*\d{4}년\s*\d+주차[\s\S]*?인증을\s*받는다\.', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'써클차트에서는\s*HUNTR\/X[\s\S]*?인증을\s*받는다\.', '', raw_content, flags=re.IGNORECASE)
    
    # 짤e몽땅 헤더 리스트
    raw_content = re.sub(r'^\d+\.\s*"[^"]+"\s*…[^\n]+\n', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'^[1-9]\d*\.\s+[^\n]+\n', '', raw_content, flags=re.MULTILINE)
    raw_content = re.sub(r'퇴근길\s*\'짤\'로\s*보는\s*뉴스,\s*<짤e몽땅>입니다\.', '', raw_content, flags=re.IGNORECASE)
    
    # 짤e몽땅 푸터
    raw_content = re.sub(r'\[.*?디지털뉴스부\s*인턴기자[\s\S]*?<짤e몽땅>입니다\.', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\.\s*\[박설아\s*디지털뉴스부\s*인턴기자\s*\]', '.', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\[박설아\s*디지털뉴스부\s*인턴기자\s*\]', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\[[가-힣]+\s*디지털뉴스부\s*인턴기자\s*\]', '', raw_content, flags=re.IGNORECASE)
    
    # 포트나이트 홈페이지 안내
    raw_content = re.sub(r'\'케이팝\s*데몬\s*헌터스\'\s*협업에\s*관한\s*자세한\s*내용은\s*포트나이트\s*홈페이지\s*내\s*블로그에서\s*확인할\s*수\s*있다\.', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'협업에\s*관한\s*자세한\s*내용은\s*포트나이트\s*홈페이지\s*내\s*블로그에서\s*확인할\s*수\s*있다\.', '', raw_content, flags=re.IGNORECASE)
    
    # 서울경제 관련뉴스 블록
    raw_content = re.sub(r'\'사상\s*첫\'.*?\[마켓시그널\]', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\d{4}년\s*\d+월\d+일\([가-힣]\).*?\[ON\s*AIR\s*서울경제\]', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'장동혁\s*"李정부.*?"', '', raw_content, flags=re.IGNORECASE)
    
    # 저작권/무단전재/재배포 금지 패턴 (모든 변형 포함)
    raw_content = re.sub(r'\n저작권자\s*©\s*[^\n]*?(?:무단전재|무단\s*전재)[^\n]*?(?:재배포|재\s*배포)[^\n]*?금지[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\nⓒ[^\n]*?(?:무단전재|무단\s*전재)[^\n]*?(?:재배포|재\s*배포)[^\n]*?금지[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\.\s*\nⓒ[^\n]*?(?:무단전재|무단\s*전재)[^\n]*?(?:재배포|재\s*배포)[^\n]*?금지[^\n]*', '.', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\.\s*\n저작권자[^\n]*?(?:무단전재|무단\s*전재)[^\n]*?(?:재배포|재\s*배포)[^\n]*?금지[^\n]*', '.', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'ⓒ[^\n]*?(?:무단전재|무단\s*전재)[^\n]*?(?:재배포|재\s*배포)[^\n]*?금지[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'저작권자\s*©[^\n]*?(?:무단전재|무단\s*전재)[^\n]*?(?:재배포|재\s*배포)[^\n]*?금지[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\nCopyright\s*ⓒ\s*[^\n]*?(?:무단|전재|재배포|금지)[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\n©\s*[^\n]*?\([^)]*www\.[^)]+\)[^\n]*?(?:무단|전재|재배포|금지)[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\n※\s*저작권자[^\n]*', '', raw_content)
    raw_content = re.sub(r'\n+Copyright\s*ⓒ\s*[^\n]*?(?:무단|전재|재배포|금지)[^\n]*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\n+Copyright\s*[©ⓒ]\s*[^\n]*$', '', raw_content, flags=re.MULTILINE | re.IGNORECASE)
    raw_content = re.sub(r'\n+Copyright\s*[©ⓒ]\s*[^\n]*', '', raw_content, flags=re.IGNORECASE)
    
    # 꺽쇠괄호 저작권 패턴
    raw_content = re.sub(r'<저작권자\([cC]\)\s*연합뉴스[^>]*>', '', raw_content)
    raw_content = re.sub(r'Copyright\s*©\s*[^.]+\.\s*All rights reserved\.[^\n]*', '', raw_content)
    raw_content = re.sub(r'<ⓒ[^>]*(?:아시아경제|경제콘텐츠)[^>]*>', '', raw_content)
    raw_content = re.sub(r'©\'[^\']*\'\s*아주경제\.[^\n]*', '', raw_content)
    raw_content = re.sub(r'<저작권자[^>]*>', '', raw_content)
    raw_content = re.sub(r'※\s*이\s*콘텐츠는\s*저작권법에\s*의하여[^\n]*?금합니다\.\s*', '', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(r'\n※\s*이\s*콘텐츠는\s*저작권법에\s*의하여[^\n]*?금합니다\.\s*', '', raw_content, flags=re.IGNORECASE)
    
    # Copyright 직접 제거
    raw_content = raw_content.replace('\nCopyright', '')
    raw_content = raw_content.replace('\n\nCopyright', '')
    raw_content = raw_content.replace('Copyright ⓒ', '')
    raw_content = raw_content.replace('Copyright ©', '')
    
    # 반복 문자 패턴
    raw_content = re.sub(r'^([가-힣]\s*){3,}\n', '', raw_content, flags=re.MULTILINE)
    
    # 기자 페이지 링크
    raw_content = re.sub(r'[가-힣\s]+기자\s+기자페이지', '', raw_content)
    
    # 후원 안내
    raw_content = re.sub(r'Fn투데이는 여러분의 후원금을 귀하게 쓰겠습니다\.', '', raw_content)
    
    # ═══════════════════════════════════════════════════════
    # STEP 11: 라인별 필터링
    # ═══════════════════════════════════════════════════════
    lines = [line.strip() for line in raw_content.split('\n')]
    
    filtered_lines = []
    for line in lines:
        # 기본 필터
        if not line or len(line) < 3:
            continue
        if line in ['.', '=', '(', ')']:
            continue
        
        # 슬래시 관련 라인
        if line == '/':
            continue
        if re.match(r'^\/[가-힣]*$', line):
            continue
        if re.match(r'^\/\s*$', line):
            continue
        
        # viewer 단독 단어
        if re.match(r'^viewer$', line, re.IGNORECASE):
            continue
        
        # YTN 단독 라인
        if re.match(r'^YTN$', line, re.IGNORECASE):
            continue
        
        # 큰사진보기 패턴
        if re.search(r'큰사진보기', line, re.IGNORECASE):
            continue
        if re.search(r'관련사진보기', line, re.IGNORECASE):
            continue
        
        # 영상 제작진 정보
        if re.match(r'^영상기자\s*[:：]', line, re.IGNORECASE):
            continue
        if re.match(r'^영상편집\s*[;；:：]', line, re.IGNORECASE):
            continue
        
        # YTN 제보 관련
        if re.search(r'당신의 제보가 뉴스가 됩니다', line, re.IGNORECASE):
            continue
        if re.search(r'YTN\s*검색해\s*채널\s*추가', line, re.IGNORECASE):
            continue
        
        # 사진 확대
        if re.match(r'^사진\s*확대$', line, re.IGNORECASE):
            continue
        
        # Credits
        if re.match(r'^Credits\s+', line, re.IGNORECASE):
            continue
        
        # SNS 캡처
        if re.match(r'^SNS\s*캡처$', line, re.IGNORECASE):
            continue
        
        # 좋아요/나빠요
        if re.match(r'^좋아요\s+\d+\s+나빠요\s+\d+$', line, re.IGNORECASE):
            continue
        if re.search(r'좋아요\s+\d+\s+나빠요\s+\d+', line, re.IGNORECASE):
            continue
        
        # 리걸타임즈
        if re.match(r'^리걸타임즈$', line, re.IGNORECASE):
            continue
        
        # 기자/특파원 패턴 (100자 이하 라인만)
        if len(line) < 100:
            if re.match(r'^[가-힣]{2,4}\s*(기자|특파원)\s*$', line):
                continue
            if re.match(r'^[가-힣]{2,4}\s*(기자|특파원)\s*[\/\|]', line):
                continue
            if re.search(r'[가-힣]{2,4}\s*(기자|특파원)\s*(구독|페이지|기자페이지)', line):
                continue
            if re.match(r'^[가-힣]{2,4}\s*기자\s*\(\s*\)$', line):
                continue
        
        # 도시/통신사 연합뉴스 라인
        if re.match(r'^[가-힣]+\/(로이터|AFP|AP|블룸버그|Getty Images)\s+연합뉴스', line):
            continue
        
        # 광고 라인
        if re.match(r'^광고$', line):
            continue
        
        # 뉴시스 패턴
        if re.match(r'^\[([가-힣]+)=뉴시스\]', line):
            continue
        if re.search(r'@newsis\.com', line):
            continue
        
        # 사진 관련
        if re.match(r'^\(사진\s*=', line):
            continue
        if re.match(r'^\(사진출처=', line):
            continue
        if re.match(r'^<사진출처=', line):
            continue
        if re.match(r'^사진제공\s*[｜|]', line):
            continue
        if re.match(r'^사진\s*출처,', line):
            continue
        if re.match(r'^사진\s*설명,', line):
            continue
        if re.match(r'^사진\s*제공\s*=', line):
            continue
        if re.match(r'^[▲▼]\s*사진\s*=', line):
            continue
        if re.match(r'^[▲▼]\s*출처\s*[:：=]', line):
            continue
        if re.match(r'^\/사진\s*=\s*[가-힣]+\s*기자$', line):
            continue
        if re.match(r'^\/\s*사진\s*제공\s*=', line):
            continue
        if re.match(r'^\([가-힣\s]+\s*제공\)$', line):
            continue
        if re.match(r'^사진\s*\/\s*gettyimagesBank$', line, re.IGNORECASE):
            continue
        
        # BBC 스타일
        if re.match(r'^기자,\s*[^\n]+기자', line):
            continue
        
        # 날짜 패턴
        if re.match(r'^\d{4}년\s*\d{1,2}월\s*\d{1,2}일$', line):
            continue
        if re.match(r'^\d{4}\.\d{1,2}\.\d{1,2}\.', line):
            continue
        
        # 내외뉴스통신
        if re.match(r'^\[[^\]]+\]\s*[가-힣\s]+기자$', line):
            continue
        if re.match(r'^내외뉴스통신,\s*NBNNEWS$', line):
            continue
        if re.match(r'^기사\s*URL\s*:', line):
            continue
        if re.match(r'^\|\s*[^\|]+=[가-힣\s]+기자\s*\|$', line):
            continue
        
        # 방송사 UI
        if re.match(r'^기자별\s*뉴스$', line):
            continue
        if re.match(r'^NEWS$', line):
            continue
        if re.match(r'^화면\s*프린트$', line):
            continue
        if re.match(r'^TJB\s*대전방송$', line):
            continue
        if re.match(r'^\[채널A\s*뉴스\]\s*구독하기$', line):
            continue
        if re.search(r'채널A\s*뉴스', line):
            continue
        if re.match(r'^MBC뉴스는 24시간', line):
            continue
        
        # 동영상 UI
        if re.match(r'^(Cancel|live|CC|1x|2x|Speed|Subtitles)$', line):
            continue
        if re.match(r'^\d{2}:\d{2}$', line):
            continue
        if re.match(r'^동영상\s*고정\s*취소$', line):
            continue
        if re.match(r'^동영상\s*고정$', line):
            continue
        if re.match(r'^재생$|^일시정지$|^음소거$', line):
            continue
        if re.match(r'^전체재생$', line):
            continue
        
        # 조선일보 패턴
        if re.match(r'^\d{6}\s+여론\d+', line):
            continue
        if re.search(r'매일\s*조선일보에\s*실린\s*칼럼', line):
            continue
        if re.search(r'뉴스레터를\s*받아보세요', line):
            continue
        if re.search(r'\'5분\s*칼럼\'\s*더보기', line):
            continue
        
        # 구독 관련
        if re.match(r'^구독수$', line):
            continue
        if re.match(r'^구독$', line):
            continue
        if re.match(r'^\d{1,5}$', line):
            continue
        
        # 해시태그
        if len(line) < 30 and re.match(r'^[a-zA-Z가-힣]+$', line):
            if re.match(r'^(케데헌|케이팝데몬헌터스|kpopdemonhunters|마텔|해즈브로|크리스마스|넷플릭스|구독|태평로)$', line):
                continue
        
        # 네비게이션
        if re.match(r'^관련\s*기사$', line):
            continue
        if re.match(r'^이전\s+다음$', line):
            continue
        if re.match(r'^좋아요$|^응원수$', line):
            continue
        if re.match(r'^최신뉴스$', line):
            continue
        if re.match(r'^더보기$', line):
            continue
        if re.match(r'^많이\s*본\s*뉴스$', line):
            continue
        if re.match(r'^다른기사보기$', line):
            continue
        if re.match(r'^돌아가기$', line):
            continue
        if re.match(r'^댓글을\s*입력해주세요$', line):
            continue
        
        # 표/구조
        if re.match(r'^구분\s+내용$', line):
            continue
        if re.match(r'^작품명|^제작|^공개 예정|^전편 공개|^특징|^흥행|^연출|^핵심 주제|^기대 포인트', line):
            continue
        
        # 저작권/제보
        if re.search(r'저작권자.*?©.*?무단.*?재배포.*?금지', line, re.IGNORECASE):
            continue
        if re.search(r'ⓒ.*?무단.*?재배포.*?금지', line, re.IGNORECASE):
            continue
        if re.search(r'제보하기', line):
            continue
        if '▷' in line:
            continue
        if line.startswith('■'):
            continue
        if re.search(r'\([^)]*=\s*연합뉴스\)', line):
            continue
        if re.search(r'후원금을 귀하게 쓰겠습니다', line):
            continue
        if re.match(r'^<\s*저작권자', line):
            continue
        if re.search(r'Copyright\s*©', line):
            continue
        if re.search(r'제보는\s*카카오톡', line):
            continue
        if re.search(r'※\s*이\s*콘텐츠는\s*저작권법', line):
            continue
        
        # 블로그/UI
        if line.startswith('#'):
            continue
        if re.match(r'^출처\s*[:：]', line):
            continue
        if re.match(r'^인쇄$', line):
            continue
        if line.startswith('📸'):
            continue
        
        # 언론사 구분자
        if re.match(r'^문화뉴스\s*\/\s*$', line):
            continue
        
        # 연합뉴스 구분자
        if re.match(r'^\/\s*연합뉴스\s*$', line):
            continue
        
        # 짤e몽땅 리스트 항목
        if re.match(r'^\d+\.\s*"', line):
            continue
        if re.match(r'^\d+\.\s+[^\n]+배우\s+키아누\s+리브스', line):
            continue
        
        # 포트나이트 라인 필터
        if re.search(r'협업에\s*관한\s*자세한\s*내용은\s*포트나이트', line, re.IGNORECASE):
            continue
        
        # 서울경제 관련뉴스 라인 필터
        if re.search(r'\'사상\s*첫\'.*\[마켓시그널\]', line):
            continue
        if re.search(r'\d{4}년\s*\d+월\d+일\([가-힣]\).*\[ON\s*AIR', line):
            continue
        if re.search(r'장동혁\s*"李정부', line):
            continue
        
        # 기사의 이해를 돕기 위한 자료
        if re.search(r'기사의\s*이해를\s*돕기\s*위한\s*자료', line, re.IGNORECASE):
            continue
        
        filtered_lines.append(line)
    
    # ═══════════════════════════════════════════════════════
    # STEP 12: 후처리 (공백 정리)
    # ═══════════════════════════════════════════════════════
    txt = '\n'.join(filtered_lines)
    txt = re.sub(r'https?:\/\/[^\s)]+', '', txt)
    txt = re.sub(r'\n\?[a-zA-Z0-9_=&]+', '', txt)
    txt = re.sub(r'\*\*', '', txt)
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    txt = re.sub(r' {2,}', ' ', txt)
    txt = re.sub(r'\[\s*\n', '\n', txt)
    txt = re.sub(r'\.\s*\[\s*$', '.', txt, flags=re.MULTILINE)
    txt = txt.strip()
    
    # ═══════════════════════════════════════════════════════
    # STEP 13: 최종 정리 (끝부분 메타데이터)
    # ═══════════════════════════════════════════════════════
    
    # 괄호 안 기자 정보
    txt = re.sub(r'\([^)]*기자\)\s*', '', txt)
    
    # 사진/영상/그래픽 크레딧
    txt = re.sub(r'\n*사진\s*[=:：]\s*[^\n]*기자\s*$', '', txt)
    txt = re.sub(r'\n*영상\s*[=:：]\s*[^\n]*기자\s*$', '', txt)
    txt = re.sub(r'\n*그래픽\s*[=:：]\s*[^\n]*기자\s*$', '', txt)
    
    # 기자 이메일/소개
    txt = re.sub(r'\n*[가-힣]{2,4}\s*기자\s*[a-zA-Z0-9._-]+@[^\s]+\s*$', '', txt)
    txt = re.sub(r'\n*[가-힣]{2,4}\s*기자\s*\/\s*경제를 읽는[^\n]*$', '', txt)
    txt = re.sub(r'\n*[가-힣]{2,4}\s*기자\s*[a-zA-Z0-9._-]+@[^\s]+(\s+[가-힣]{2,4}\s*기자\s*[a-zA-Z0-9._-]+@[^\s]+)*\s*$', '', txt)
    
    # 기자 빈 괄호
    txt = re.sub(r'\n*[가-힣]{2,4}\s*기자\s*\(\s*\)\s*$', '', txt)
    txt = re.sub(r'[가-힣]{2,4}\s*기자\s*\(\s*\)', '', txt)
    
    # 방송 언론사
    txt = re.sub(r'\n*[가-힣]{2,4}\s*머니투데이방송\s*MTN\s*기자\s*$', '', txt)
    
    # MBN뉴스 패턴
    txt = re.sub(r'\n*MBN뉴스\s+[가-힣]{2,4}입니다\.\s*\[\s*\]\s*$', '', txt)
    txt = re.sub(r'MBN뉴스\s+[가-힣]{2,4}입니다\.\s*\[\s*\]', '', txt)
    
    # KBS 뉴스 패턴
    txt = re.sub(r'\n*KBS\s*뉴스\s*[가-힣]{2,4}입니다\.\s*$', '', txt)
    txt = re.sub(r'\nKBS\s*뉴스\s*[가-힣]{2,4}입니다\.$', '', txt)
    txt = re.sub(r'KBS\s*뉴스\s*[가-힣]{2,4}입니다\.\s*$', '', txt)
    
    # YTN 기자 이름
    txt = re.sub(r'\n지금까지\s+YTN[^\n]*에서\s+YTN\s+[가-힣]{2,4}입니다\.\s*\nYTN\s+[가-힣]{2,4}\s*\(\s*\)\s*\n\[저작권자\([cC]\)\s*YTN[^\]]*\]\s*$', '', txt)
    txt = re.sub(r'\n*YTN\s+[가-힣]{2,4}\s*\(\s*\)\s*$', '', txt)
    txt = re.sub(r'YTN\s+[가-힣]{2,4}\s*\(\s*\)\s*$', '', txt)
    txt = re.sub(r'\n\[저작권자\([cC]\)\s*YTN[^\]]*\]\s*$', '', txt)
    
    # 짤e몽땅 푸터 마지막 처리
    txt = re.sub(r'\.\s*\[박설아\s*디지털뉴스부\s*인턴기자\s*\]', '.', txt, flags=re.IGNORECASE)
    txt = re.sub(r'\[[가-힣]+\s*디지털뉴스부\s*인턴기자\s*\]', '', txt, flags=re.IGNORECASE)
    
    # 끝부분 기자/특파원 이름
    txt = re.sub(r'\n+[가-힣]{2,4}\s*(기자|특파원)(\s|\n)*$', '', txt)
    txt = re.sub(r'\n[가-힣]{2,4}\s*(기자|특파원)(\s|\n)*$', '', txt)
    txt = re.sub(r'[가-힣]{2,4}\s*(기자|특파원)(\s|\n)*$', '', txt)
    txt = re.sub(r'\.\s*\n+[가-힣]{2,4}\s*(기자|특파원)(\s|\n)*$', '.', txt)
    txt = re.sub(r'\n+[가-힣]{2,4}\s*(기자|특파원)(\s|\n)*$', '', txt)
    txt = re.sub(r'\n[가-힣]{2,4}\s*(기자|특파원)(\s|\n)*$', '', txt)
    txt = re.sub(r'[가-힣]{2,4}\s*(기자|특파원)(\s|\n)*$', '', txt)
    
    # 한국경제 구독 안내
    txt = re.sub(r'\n(싫어요|후속기사 원해요)(\s|\n)*$', '', txt)
    txt = re.sub(r'\n한국경제 구독신청(\s|\n)*$', '', txt)
    txt = re.sub(r'\n모바일한경 보기(\s|\n)*$', '', txt)
    txt = re.sub(r'\n귀 기울여 듣겠습니다\.(\s|\n)*$', '', txt)
    txt = re.sub(r'\n지면\s*A\d+(\s|\n)*$', '', txt)
    txt = re.sub(r'\n글자크기 조절(\s|\n)*$', '', txt)
    txt = re.sub(r'\n기사 스크랩(\s|\n)*$', '', txt)
    txt = re.sub(r'\n클린뷰(\s|\n)*$', '', txt)
    
    txt = txt.strip()
    
    return txt


def is_legal_notice_page(content: str) -> bool:
    """
    법적고지/약관 페이지 감지
    
    채널A 등에서 본문 대신 법적고지 페이지만 가져오는 경우 감지
    """
    if not content or len(content) < 50:
        return False
    
    content_stripped = content.strip()
    
    # 패턴 1: "법적고지"로 시작
    if content_stripped.startswith('법적고지'):
        return True
    
    # 패턴 2: 채널A 법적고지 특정 문구
    if '채널A에서 제공하는 콘텐츠에 대하여' in content and \
       '법령을 준수하기 위하여' in content and \
       '기자' not in content:
        return True
    
    # 패턴 3: 일반적인 법적고지/약관 키워드 조합
    legal_keywords = ['법적고지', '면책조항', '이용약관', '개인정보처리방침']
    legal_count = sum(1 for keyword in legal_keywords if keyword in content_stripped)
    
    # 법적 키워드가 2개 이상이고, 뉴스 관련 키워드가 없는 경우
    news_keywords = ['기자', '취재', '보도', '기사', '뉴스']
    has_news_content = any(keyword in content_stripped for keyword in news_keywords)
    
    if legal_count >= 2 and not has_news_content:
        return True
    
    return False


def extract_article(url: str) -> dict:
    """
    newspaper3k로 기사 추출
    
    품질 기준:
    - 법적고지 페이지: 실패
    - 본문 100자 미만: 실패
    - 본문 100자 이상: 성공
    
    본문 정제:
    - clean_news_body 함수를 통해 기자 정보, UI 요소, 메타데이터 제거
    """
    try:
        # Article 객체 생성
        article = Article(url, language='ko')
        
        # 다운로드 및 파싱
        article.download()
        article.parse()
        
        # 본문 추출
        content = article.text or ""
        content_stripped = content.strip()
        
        # 1단계: 법적고지 페이지 감지 (정제 전)
        if is_legal_notice_page(content_stripped):
            return {
                "success": False,
                "url": url,
                "content": "",
                "content_length": 0,
                "extraction_method": "newspaper3k",
                "error": "법적고지/약관 페이지가 감지되었습니다. JavaScript 렌더링이 필요한 사이트입니다. Tavily API 사용을 권장합니다."
            }
        
        # 2단계: 본문 정제 (기자 정보, UI 요소, 메타데이터 제거)
        cleaned_content = clean_news_body(content_stripped)
        cleaned_content_length = len(cleaned_content)
        
        # 3단계: 정제된 본문 길이 체크 (100자 이하면 실패)
        if cleaned_content_length < 100:
            return {
                "success": False,
                "url": url,
                "content": cleaned_content,
                "content_length": cleaned_content_length,
                "extraction_method": "newspaper3k",
                "error": f"본문이 너무 짧습니다 ({cleaned_content_length}자). JavaScript 렌더링 사이트일 가능성 높음. Tavily API 사용을 권장합니다."
            }
        
        # 4단계: 100자 이상이면 성공
        return {
            "success": True,
            "url": url,
            "content": cleaned_content,
            "content_length": cleaned_content_length,
            "extraction_method": "newspaper3k",
            "error": None
        }
        
    except Exception as e:
        error_message = str(e)
        return {
            "success": False,
            "url": url,
            "content": "",
            "content_length": 0,
            "extraction_method": "newspaper3k",
            "error": f"추출 실패: {error_message}"
        }

@app.get("/")
def root():
    """API 정보"""
    return {
        "service": "News Extractor API",
        "version": "2.3.0",
        "description": "newspaper3k 기반 뉴스 본문 추출 (품질 검증 + 법적고지 감지 + 본문 정제)",
        "method": "newspaper3k",
        "features": [
            "법적고지/약관 페이지 감지",
            "본문 100자 이상 품질 검증",
            "기자 정보, UI 요소, 메타데이터 자동 제거"
        ],
        "cleaning_patterns": [
            "블로그 헤더",
            "기자 정보 (이름, 이메일, 소속)",
            "사진/영상 출처 및 크레딧",
            "방송 대본/인터뷰 마크업",
            "영상 제작 정보",
            "제보/연락처 정보",
            "UI 요소 (버튼, 네비게이션)",
            "저작권 표시",
            "광고 및 구독 안내"
        ],
        "endpoints": {
            "POST /extract": "뉴스 본문 추출",
            "GET /health": "헬스체크"
        },
        "notes": "법적고지 페이지 또는 100자 미만 본문은 실패로 처리하며, 모든 응답은 HTTP 200으로 반환됩니다."
    }


@app.get("/health")
def health_check():
    """헬스체크"""
    return {
        "status": "healthy",
        "service": "news-extractor-api",
        "method": "newspaper3k",
        "version": "2.3.0",
        "features": ["content_cleaning", "legal_notice_detection", "quality_validation"]
    }


@app.post("/extract")
async def extract(request: ExtractRequest):
    """
    뉴스 본문 추출 (자동 정제 포함)
    
    - **url**: 추출할 뉴스 URL
    
    Returns:
    - success: 성공 여부 (법적고지 X + 본문 100자 이상이면 True)
    - url: 요청한 URL
    - content: 정제된 기사 본문 (기자 정보, UI 요소 등 제거됨)
    - content_length: 본문 길이
    - extraction_method: 추출 방법 (newspaper3k)
    - error: 에러 메시지 (실패 시)
    
    Note:
    - 법적고지/약관 페이지가 감지되면 success=False를 반환합니다.
    - 본문이 100자 미만이면 success=False를 반환합니다.
    - 이 경우 Tavily API 사용을 권장합니다.
    - 본문은 자동으로 정제되어 기자 정보, 사진 출처, UI 요소, 저작권 표시 등이 제거됩니다.
    - ⭐ 모든 응답은 HTTP 200으로 반환됩니다 (워크플로우 중단 방지)
    """
    try:
        # URL을 안전하게 문자열로 변환
        url_str = str(request.url) if request.url else ""
        if not url_str:
            raise ValueError("URL이 제공되지 않았습니다.")
        
        result = extract_article(url_str)
        
        # ⭐ 핵심: 성공/실패 모두 HTTP 200 OK로 반환
        # n8n의 Always Output Data와 함께 사용하여 워크플로우 중단 방지
        return JSONResponse(
            status_code=200,
            content=result
        )
        
    except Exception as e:
        # 예상치 못한 에러도 200으로 반환
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
                "extraction_method": "newspaper3k",
                "error": f"서버 내부 오류: {str(e)}"
            }
        )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)