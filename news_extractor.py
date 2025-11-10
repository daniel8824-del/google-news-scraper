# newspaper3k 기반 뉴스 추출 API
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from newspaper import Article
from urllib.parse import urlparse
import uvicorn

app = FastAPI(
    title="News Extractor API",
    description="newspaper3k 기반 뉴스 본문 추출 API",
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
        "version": "1.0.0",
        "description": "newspaper3k 기반 뉴스 본문 추출",
        "method": "newspaper3k",
        "endpoints": {
            "POST /extract": "뉴스 본문 추출",
            "GET /health": "헬스체크"
        }
    }


@app.get("/health")
def health_check():
    """헬스체크"""
    return {
        "status": "healthy",
        "service": "news-extractor-api",
        "method": "newspaper3k"
    }


@app.post("/extract", response_model=ExtractResponse)
async def extract(request: ExtractRequest):
    """
    뉴스 본문 추출
    
    - **url**: 추출할 뉴스 URL
    
    Returns:
    - success: 성공 여부
    - title: 기사 제목
    - content: 기사 본문
    - content_length: 본문 길이
    - authors: 저자 목록
    - publish_date: 발행일
    - top_image: 대표 이미지 URL
    """
    result = extract_article(str(request.url))
    
    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=f"추출 실패: {result['error']}"
        )
    
    return result


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)