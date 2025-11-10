# newspaper3k 기반 뉴스 추출 API (v2.2)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, HttpUrl
from typing import Optional
from newspaper import Article
from urllib.parse import urlparse
import json
import re
import uvicorn

app = FastAPI(
    title="News Extractor API",
    description="newspaper3k 기반 뉴스 본문 추출 API",
    version="2.2.0"
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
    url_str, domain = await extract_url_from_request(request, body_bytes)
    
    return JSONResponse(
        status_code=200,  # HTTP 200으로 반환 (워크플로우 중단 방지)
        content={
            "success": False,
            "url": url_str,
            "domain": domain,
            "title": "",
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
    url_str, domain = await extract_url_from_request(request)
    
    return JSONResponse(
        status_code=200,  # HTTP 200으로 반환 (워크플로우 중단 방지)
        content={
            "success": False,
            "url": url_str,
            "domain": domain,
            "title": "",
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
    domain: str
    title: str
    content: str
    content_length: int
    extraction_method: str
    error: Optional[str] = None


def get_domain(url: str) -> str:
    """URL에서 도메인 추출"""
    return urlparse(url).netloc


async def extract_url_from_request(request: Request, body_bytes: bytes = None) -> tuple[str, str]:
    """
    요청에서 URL을 추출 시도
    Returns: (url_str, domain)
    """
    # body_bytes가 제공된 경우 사용 (RequestValidationError에서)
    if body_bytes:
        body_text = None
        try:
            body_text = body_bytes.decode('utf-8')
            # JSON 파싱 시도
            body = json.loads(body_text)
            if isinstance(body, dict) and "url" in body:
                url_str = str(body["url"])
                return url_str, get_domain(url_str)
        except:
            pass
        
        # JSON 파싱 실패 시 텍스트에서 URL 패턴 찾기
        if body_text:
            try:
                url_match = re.search(r'https?://[^\s"\'<>]+', body_text)
                if url_match:
                    url_str = url_match.group(0)
                    return url_str, get_domain(url_str)
            except:
                pass
    
    # body_bytes가 없는 경우 요청 본문 읽기 시도
    try:
        body = await request.json()
        if isinstance(body, dict) and "url" in body:
            url_str = str(body["url"])
            return url_str, get_domain(url_str)
    except:
        pass
    
    return "", ""


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
        content_length = len(content_stripped)
        
        # 1단계: 법적고지 페이지 감지
        if is_legal_notice_page(content_stripped):
            return {
                "success": False,
                "url": url,
                "domain": get_domain(url),
                "title": article.title or "",
                "content": "",
                "content_length": 0,
                "extraction_method": "newspaper3k",
                "error": "법적고지/약관 페이지가 감지되었습니다. JavaScript 렌더링이 필요한 사이트입니다. Tavily API 사용을 권장합니다."
            }
        
        # 2단계: 본문 길이 체크 (100자 이하면 실패)
        if content_length < 100:
            return {
                "success": False,
                "url": url,
                "domain": get_domain(url),
                "title": article.title or "",
                "content": content_stripped,
                "content_length": content_length,
                "extraction_method": "newspaper3k",
                "error": f"본문이 너무 짧습니다 ({content_length}자). JavaScript 렌더링 사이트일 가능성 높음. Tavily API 사용을 권장합니다."
            }
        
        # 3단계: 100자 이상이면 성공
        return {
            "success": True,
            "url": url,
            "domain": get_domain(url),
            "title": article.title or "",
            "content": content_stripped,
            "content_length": content_length,
            "extraction_method": "newspaper3k",
            "error": None
        }
        
    except Exception as e:
        error_message = str(e)
        return {
            "success": False,
            "url": url,
            "domain": get_domain(url),
            "title": "",
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
        "version": "2.2.0",
        "description": "newspaper3k 기반 뉴스 본문 추출 (품질 검증 + 법적고지 감지)",
        "method": "newspaper3k",
        "quality_checks": [
            "법적고지/약관 페이지 감지",
            "본문 100자 이상"
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
        "version": "2.2.0"
    }


@app.post("/extract")
async def extract(request: ExtractRequest):
    """
    뉴스 본문 추출
    
    - **url**: 추출할 뉴스 URL
    
    Returns:
    - success: 성공 여부 (법적고지 X + 본문 100자 이상이면 True)
    - url: 요청한 URL
    - domain: 도메인
    - title: 기사 제목
    - content: 기사 본문
    - content_length: 본문 길이
    - extraction_method: 추출 방법 (newspaper3k)
    - error: 에러 메시지 (실패 시)
    
    Note:
    - 법적고지/약관 페이지가 감지되면 success=False를 반환합니다.
    - 본문이 100자 미만이면 success=False를 반환합니다.
    - 이 경우 Tavily API 사용을 권장합니다.
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
            domain = get_domain(url_str) if url_str else ""
        except:
            url_str = ""
            domain = ""
        
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "url": url_str,
                "domain": domain,
                "title": "",
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