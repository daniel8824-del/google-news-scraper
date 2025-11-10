# Python 3.12 기반 이미지 사용
FROM python:3.12-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필수 패키지 설치
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libxml2-dev \
    libxslt1-dev \
    wget \
    gnupg \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt 복사 및 의존성 설치
COPY requirements.txt .
# pip 업그레이드 (tiktoken prebuilt wheel 사용을 위해)
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 포트 노출 (Railway가 자동으로 PORT 환경변수를 설정)
EXPOSE 8000

# 환경변수 설정
ENV PYTHONUNBUFFERED=1

# 애플리케이션 실행
# Railway는 PORT 환경변수를 제공하므로 이를 사용
CMD python -c "import uvicorn; from news_extractor import app; import os; port = int(os.environ.get('PORT', 8000)); uvicorn.run(app, host='0.0.0.0', port=port)"