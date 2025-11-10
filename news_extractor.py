# newspaper3k 기반 뉴스 추출 API (v2.0 - 500 에러 수정)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from newspaper import Article
from urllib.parse import urlparse
import uvicorn

app = FastAPI(
    title="News Extractor API",
    description="newspaper3k 기반 뉴스 본문 추출 API (품질 검증 포함)",
    version="2.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    authors: List[str]
    publish_date: Optional[str]
    top_image: Optional[str]
    extraction_method: str
    error: Optional[str] = None


def get_domain(url: str) -> str:
    """URL에서 도메인 추출"""
    return urlparse(url).netloc


def extract_article(url: str) -> dict:
    """
    newspaper3k로 기사 추출
    
    품질 기준:
    - 본문 100자 이상: 성공
    - 본문 100자 미만: 실패
    """
    try:
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
                "domain": get_domain(url),
                "title": article.title or "",
                "content": content_stripped,
                "content_length": content_length,
                "authors": article.authors or [],
                "publish_date": str(article.publish_date) if article.publish_date else None,
                "top_image": article.top_image or None,
                "extraction_method": "newspaper3k",
                "error": f"본문이 너무 짧습니다 ({content_length}자). JavaScript 렌더링 사이트일 가능성 높음. Tavily API 사용을 권장합니다."
            }
        
        # 100자 이상이면 성공
        return {
            "success": True,
            "url": url,
            "domain": get_domain(url),
            "title": article.title or "",
            "content": content_stripped,
            "content_length": content_length,
            "authors": article.authors or [],
            "publish_date": str(article.publish_date) if article.publish_date else None,
            "top_image": article.top_image or None,
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
            "authors": [],
            "publish_date": None,
            "top_image": None,
            "extraction_method": "newspaper3k",
            "error": f"추출 실패: {error_message}"
        }

@app.get("/")
def root():
    """API 정보"""
    return {
        "service": "News Extractor API",
        "version": "2.0.0",
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
        "version": "2.0.0"
    }


@app.post("/extract")
async def extract(request: ExtractRequest):
    """
    뉴스 본문 추출
    
    - **url**: 추출할 뉴스 URL
    
    Returns:
    - success: 성공 여부 (본문 100자 이상이면 True)
    - title: 기사 제목
    - content: 기사 본문
    - content_length: 본문 길이
    - authors: 저자 목록
    - publish_date: 발행일
    - top_image: 대표 이미지 URL
    - error: 에러 메시지 (실패 시)
    
    Note:
    - 본문이 100자 미만이면 success=False를 반환합니다.
    - 이 경우 Tavily API 사용을 권장합니다.
    - ⭐ 모든 응답은 HTTP 200으로 반환됩니다 (워크플로우 중단 방지)
    """
    try:
        result = extract_article(str(request.url))
        
        # ⭐ 핵심 변경: 성공/실패 모두 HTTP 200 OK로 반환
        # n8n의 Always Output Data와 함께 사용하여 워크플로우 중단 방지
        return JSONResponse(
            status_code=200,
            content=result
        )
        
    except Exception as e:
        # 예상치 못한 에러도 200으로 반환
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "url": str(request.url),
                "domain": get_domain(str(request.url)),
                "title": "",
                "content": "",
                "content_length": 0,
                "authors": [],
                "publish_date": None,
                "top_image": None,
                "extraction_method": "newspaper3k",
                "error": f"서버 내부 오류: {str(e)}"
            }
        )


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)