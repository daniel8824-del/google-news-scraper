# GitHub 및 Railway 배포 가이드

## 1. GitHub 저장소 생성 및 푸시

### GitHub에서 새 저장소 생성
1. GitHub.com 접속
2. "New repository" 클릭
3. 저장소 이름 입력 (예: `news-extractor`)
4. Public 또는 Private 선택
5. "Create repository" 클릭

### 로컬에서 Git 초기화 및 푸시

```bash
# Git 초기화
git init

# 파일 추가
git add .

# 첫 커밋
git commit -m "Initial commit: News Extractor API"

# GitHub 저장소 연결 (YOUR_USERNAME과 REPO_NAME을 실제 값으로 변경)
git remote add origin https://github.com/YOUR_USERNAME/REPO_NAME.git

# 메인 브랜치로 설정
git branch -M main

# 푸시
git push -u origin main
```

## 2. Railway 배포

### Railway 계정 생성
1. https://railway.app 접속
2. GitHub 계정으로 로그인

### 프로젝트 배포
1. Railway 대시보드에서 "New Project" 클릭
2. "Deploy from GitHub repo" 선택
3. 방금 만든 GitHub 저장소 선택
4. Railway가 자동으로 Dockerfile을 감지하여 배포 시작

### 환경 변수 설정 (필요시)
Railway 대시보드 → 프로젝트 → Variables에서 환경 변수 추가 가능

### 도메인 설정
1. 프로젝트 → Settings → Generate Domain
2. 자동으로 `프로젝트명.up.railway.app` 형식의 도메인 생성

## 3. 배포 확인

배포 완료 후:
- `https://YOUR_PROJECT.up.railway.app/health` 접속하여 헬스체크
- `https://YOUR_PROJECT.up.railway.app/docs` 접속하여 API 문서 확인

## 4. 자동 배포

GitHub에 푸시하면 Railway가 자동으로 재배포합니다!

