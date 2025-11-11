# newspaper3k 기반 뉴스 추출 API (v2.1 - 일관된 응답 형식 보장)
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
    description="newspaper3k 기반 뉴스 본문 추출 API (품질 검증 포함)",
    version="2.1.0"
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


def extract_article(url: str) -> dict:
    """
    newspaper3k로 기사 추출
    
    품질 기준:
    - 본문 100자 이상: 성공
    - 본문 100자 미만: 실패
    """
    try:
        # 채널A는 무조건 실패 처리 (약관 페이지 반환 문제)
        if 'ichannela.com' in url:
            return {
                "success": False,
                "url": url,
                "content": "",
                "content_length": 0,
                "extraction_method": "newspaper3k",
                "error": "채널A는 newspaper3k로 추출 불가. Playwright API를 사용하세요."
            }
        
        # Article 객체 생성
        article = Article(url, language='ko')
        
        # 다운로드 및 파싱
        article.download()
        article.parse()
        
        # 본문 길이 체크
        content = article.text or ""
        content_stripped = content.strip()
        content_length = len(content_stripped)
        
        # 핵심: 100자 이하면 실패로 처리
        if content_length < 100:
            return {
                "success": False,  # 실패로 판정
                "url": url,
                "content": content_stripped,
                "content_length": content_length,
                "extraction_method": "newspaper3k",
                "error": f"본문이 너무 짧습니다 ({content_length}자). JavaScript 렌더링 사이트일 가능성 높음. Playwright API 사용을 권장합니다."
            }
        
        # 100자 이상이면 성공
        return {
            "success": True,
            "url": url,
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
        "version": "2.1.0",
        "description": "newspaper3k 기반 뉴스 본문 추출 (품질 검증 포함)",
        "method": "newspaper3k",
        "quality_threshold": "본문 100자 이상",
        "endpoints": {
            "POST /extract": "뉴스 본문 추출",
            "GET /health": "헬스체크"
        },
        "notes": "100자 미만 본문은 실패로 처리하며, 모든 응답은 HTTP 200으로 반환됩니다."
    }


@app.get("/health")
def health_check():
    """헬스체크"""
    return {
        "status": "healthy",
        "service": "news-extractor-api",
        "method": "newspaper3k",
        "version": "2.1.0"
    }


@app.post("/extract")
async def extract(request: ExtractRequest):
    """
    뉴스 본문 추출
    
    - **url**: 추출할 뉴스 URL
    
    Returns:
    - success: 성공 여부 (본문 100자 이상이면 True)
    - url: 요청한 URL
    - content: 기사 본문
    - content_length: 본문 길이
    - extraction_method: 추출 방법 (newspaper3k)
    - error: 에러 메시지 (실패 시)
    
    Note:
    - 본문이 100자 미만이면 success=False를 반환합니다.
    - 이 경우 Playwright API 사용을 권장합니다.
    - 모든 응답은 HTTP 200으로 반환됩니다 (워크플로우 중단 방지)
    """
    try:
        # URL을 안전하게 문자열로 변환
        url_str = str(request.url) if request.url else ""
        if not url_str:
            raise ValueError("URL이 제공되지 않았습니다.")
        
        result = extract_article(url_str)
        
        # 핵심 변경: 성공/실패 모두 HTTP 200 OK로 반환
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