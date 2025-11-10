#!/bin/bash

echo "🚀 Playwright 브라우저 설치 중..."
playwright install chromium

echo "✅ Chromium 설치 완료! 서버 시작..."
python news_playwright.py