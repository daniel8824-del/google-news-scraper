# News Extractor API

newspaper3k 기반 뉴스 본문 추출 FastAPI 서비스

## 🚀 기능

- FastAPI 기반 REST API
- newspaper3k를 사용한 뉴스 본문 추출
- 한국어 뉴스 사이트 최적화
- 본문 품질 검증 (100자 이상)

## 📋 API 엔드포인트

### `GET /`
API 정보 반환

### `GET /health`
헬스체크

### `POST /extract`
뉴스 본문 추출

**Request:**
```json
{
  "url": "https://example.com/news/article"
}
```

**Response:**
```json
{
  "success": true,
  "url": "https://example.com/news/article",
  "domain": "example.com",
  "title": "기사 제목",
  "content": "기사 본문...",
  "content_length": 1234,
  "authors": ["작성자"],
  "publish_date": "2025-11-10",
  "top_image": "https://example.com/image.jpg",
  "extraction_method": "newspaper3k",
  "error": null
}
```

## 🛠️ 로컬 실행

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 서버 실행
```bash
python news_extractor.py
```

서버가 `http://localhost:8000`에서 실행됩니다.

### 3. API 문서 확인
브라우저에서 `http://localhost:8000/docs` 접속

## 🐳 Docker로 실행

```bash
docker build -t news-extractor .
docker run -p 8000:8000 news-extractor
```

## ☁️ Railway 배포

1. GitHub에 코드 푸시
2. Railway에서 GitHub 저장소 연결
3. 자동 배포 완료!

Railway는 Dockerfile을 자동으로 인식하여 배포합니다.

## 📦 의존성

- fastapi==0.104.1
- uvicorn[standard]==0.24.0
- pydantic==2.5.0
- newspaper3k==0.2.8
- beautifulsoup4==4.12.2
- lxml==4.9.3
- lxml-html-clean==0.4.3
- Pillow==10.1.0

## 📝 라이선스

MIT

