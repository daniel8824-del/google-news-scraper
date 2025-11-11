# Playwright 기반 뉴스 추출 API (v1.0 - 동적 렌더링 전용)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, HttpUrl
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import json
import re
import uvicorn

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
            "extraction_method": "playwright",
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
            "extraction_method": "playwright",
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
    Playwright로 동적 렌더링 사이트 추출
    
    안정적인 기본 전략 (모든 사이트 동일)
    """
    try:
        print(f"[Playwright] {url}")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--disable-extensions',
                    '--single-process',
                    '--disable-images',
                ]
            )
            page = await browser.new_page()
            
            # 리소스 차단
            await page.route("**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf}", lambda route: route.abort())
            
            # User-Agent 설정
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            
            # 안정적인 로딩
            try:
                await page.goto(url, wait_until='commit', timeout=30000)
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
            except PlaywrightTimeoutError:
                pass
            
            await page.wait_for_timeout(5000)
            
            try:
                await page.wait_for_selector('article, main, .post_content, .editor, .article-content', timeout=5000)
            except:
                pass
            
            html = await page.content()
            await browser.close()
            
            # 본문 추출
            soup = BeautifulSoup(html, 'html.parser')
            
            for script in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
                script.decompose()
            
            for element in soup.find_all(class_=re.compile(r'ad|advertisement|banner|sidebar|related|comment|share|social', re.I)):
                element.decompose()
            
            content_tag = (
                soup.find('article') or 
                soup.find('main') or 
                soup.find('div', class_=re.compile(r'article|content|post|entry', re.I)) or
                soup.find('div', id=re.compile(r'article|content|post|entry', re.I)) or
                soup.find('body')
            )
            
            if content_tag:
                content = content_tag.get_text(separator='\n', strip=True)
                content = re.sub(r'\n\s*\n+', '\n\n', content)
                content_stripped = content.strip()
                content_length = len(content_stripped)
            else:
                content_stripped = ""
                content_length = 0
        
        # 응답 처리
        if content_length > 0:
            # 100자 이하면 실패
            if content_length < 100:
                return {
                    "success": False,
                    "url": url,
                    "content": content_stripped,
                    "content_length": content_length,
                    "extraction_method": "playwright",
                    "error": f"본문이 너무 짧습니다 ({content_length}자). Playwright로도 충분한 내용을 추출하지 못했습니다."
                }
            
            return {
                "success": True,
                "url": url,
                "content": content_stripped,
                "content_length": content_length,
                "extraction_method": "playwright",
                "error": None
            }
        else:
            return {
                "success": False,
                "url": url,
                "content": "",
                "content_length": 0,
                "extraction_method": "playwright",
                "error": "본문을 찾을 수 없습니다."
            }
                
    except PlaywrightTimeoutError:
        return {
            "success": False,
            "url": url,
            "content": "",
            "content_length": 0,
            "extraction_method": "playwright",
            "error": "페이지 로드 타임아웃 (15초 초과)"
        }
    except Exception as e:
        return {
            "success": False,
            "url": url,
            "content": "",
            "content_length": 0,
            "extraction_method": "playwright",
            "error": f"Playwright 추출 실패: {str(e)}"
        }


@app.get("/")
def root():
    """API 정보"""
    return {
        "service": "News Extractor API (Dynamic)",
        "version": "1.0.0",
        "description": "Playwright 기반 동적 렌더링 뉴스 본문 추출",
        "method": "playwright",
        "quality_threshold": "본문 100자 이상",
        "performance": {
            "speed": "보통 (8-10초/기사)",
            "use_case": "JavaScript 렌더링 사이트"
        },
        "endpoints": {
            "POST /playwright": "Playwright로 뉴스 본문 추출",
            "GET /health": "헬스체크"
        },
        "notes": "동적 렌더링 사이트 전용. 일반 사이트는 news_extractor.py (포트 8000) 사용을 권장합니다."
    }


@app.get("/health")
def health_check():
    """헬스체크"""
    return {
        "status": "healthy",
        "service": "news-playwright-api",
        "method": "playwright",
        "version": "1.0.0"
    }


@app.post("/playwright")
async def extract_playwright(request: ExtractRequest):
    """
    Playwright로 동적 렌더링 뉴스 본문 추출
    
    - **url**: 추출할 뉴스 URL
    
    Returns:
    - success: 성공 여부 (본문 100자 이상이면 True)
    - url: 요청한 URL
    - content: 기사 본문
    - content_length: 본문 길이
    - extraction_method: 추출 방법 (playwright)
    - error: 에러 메시지 (실패 시)
    
    Note:
    - JavaScript 렌더링이 필요한 사이트에 사용
    - 처리 시간: 8-10초/기사
    - 일반 정적 사이트는 news_extractor.py의 /extract 사용 권장
    - 모든 응답은 HTTP 200으로 반환됩니다
    """
    try:
        url_str = str(request.url) if request.url else ""
        if not url_str:
            raise ValueError("URL이 제공되지 않았습니다.")
        
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
                "extraction_method": "playwright",
                "error": f"서버 내부 오류: {str(e)}"
            }
        )


if __name__ == "__main__":
    import os
    # 기본 포트 8001 사용 (8000과 구분)
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)