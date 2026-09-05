# 🚀 Vercel 배포 가이드 (비개발자용, 15분 소요)

## 준비물
- ✅ GitHub 계정 (없으면 github.com에서 무료 가입)
- ✅ Vercel 계정 (github 계정으로 바로 로그인 가능)
- ✅ 이 폴더의 파일 5개 + `api/` 폴더

## 📁 최종 폴더 구조 확인

```
ttokjae-api/
├── api/
│   ├── quote-us.js      (미국 주식 시세)
│   ├── quote-kr.js      (국내 ETF 시세)
│   ├── macros.js        (VIX, CNN F&G, VKOSPI)
│   └── search.js        (티커 자동완성)
├── package.json
├── vercel.json
├── README.md
└── DEPLOY_GUIDE.md
```

---

## 🎯 STEP 1: GitHub 저장소 생성 (5분)

### 방법 A: 웹에서 업로드 (초심자 추천)

1. **github.com** 접속 → 로그인
2. 우측 상단 **`+`** 버튼 → **"New repository"**
3. 저장소 이름: `ttokjae-finance-api` (원하는 이름 가능)
4. **"Public"** 선택 (Vercel 무료 플랜은 Private도 가능)
5. **"Create repository"** 클릭
6. 다음 페이지에서 **"uploading an existing file"** 링크 클릭
7. 이 `ttokjae-api/` 폴더 내용을 **전부 드래그 앤 드롭**
   - ⚠️ `api/` 폴더도 포함해서 올려주세요
8. 아래 **"Commit changes"** 클릭

### 방법 B: Git 명령어 (개발자용)

```bash
cd ttokjae-api/
git init
git add .
git commit -m "Initial commit: TTOKJAE finance API"
git branch -M main
git remote add origin https://github.com/[본인아이디]/ttokjae-finance-api.git
git push -u origin main
```

---

## 🎯 STEP 2: Vercel 배포 (5분)

1. **vercel.com** 접속 → **"Start Deploying"** 또는 **"Log In"**
2. **"Continue with GitHub"** 클릭 → GitHub 계정 연동 승인
3. 대시보드에서 **"Add New..."** → **"Project"** 클릭
4. 방금 만든 **`ttokjae-finance-api`** 저장소 찾아서 **"Import"** 클릭
5. 설정 화면에서:
   - **Framework Preset**: "Other" (자동 감지될 수도 있음)
   - **Root Directory**: `.` (기본값 유지)
   - **Build Command**: 비워두기
   - **Output Directory**: 비워두기
   - **Install Command**: 비워두기
6. **"Deploy"** 버튼 클릭
7. 🎉 **약 1~2분 후 배포 완료!**

배포가 끝나면 이런 URL이 생깁니다:
```
https://ttokjae-finance-api-abc123.vercel.app
```
이 URL을 **복사해두세요** — 계산기에 입력해야 합니다.

---

## 🎯 STEP 3: API 테스트 (2분)

브라우저에서 아래 URL들을 열어보세요:

### 테스트 1: 미국 주식 (VOO)
```
https://[본인URL].vercel.app/api/quote-us?ticker=VOO
```
→ JSON 데이터가 뜨면 성공 ✅

### 테스트 2: 국내 ETF (TIGER 미국S&P500)
```
https://[본인URL].vercel.app/api/quote-kr?ticker=360750
```

### 테스트 3: 매크로 지수
```
https://[본인URL].vercel.app/api/macros
```
→ vix, cnnFearGreed, vkospi 값이 나와야 함

### 테스트 4: 검색
```
https://[본인URL].vercel.app/api/search?q=TIGER&market=kr
```

---

## 🎯 STEP 4: 계산기에 API URL 연결 (1분)

1. TTOKJAE 계산기 HTML 파일을 텍스트 에디터로 열기
2. 상단 `<script>` 영역에서 다음 줄 찾기:
   ```javascript
   const API_BASE = 'https://your-vercel-url.vercel.app';
   ```
3. `your-vercel-url.vercel.app`를 **본인 Vercel URL**로 교체
4. 저장 → 업로드 완료!

---

## 🎯 STEP 5: 커스텀 도메인 연결 (선택사항)

가지고 있는 도메인 (예: `ttokjae.com`) 에 연결하고 싶다면:

1. Vercel 프로젝트 → **"Settings"** → **"Domains"**
2. `api.ttokjae.com` 같은 서브도메인 입력 → **"Add"**
3. 표시되는 **CNAME 레코드**를 본인 도메인 관리자(가비아/Cloudflare 등)에 추가
4. 5~30분 후 자동 연결 완료

---

## ❓ 자주 묻는 질문

### Q1. 비용이 진짜 무료인가요?
✅ Vercel Hobby 플랜은 **개인 용도 100% 무료**입니다.
- 월 100GB 대역폭
- 월 100시간 서버리스 실행 시간
- 카페/블로그 임베드 수준이면 평생 무료로 쓸 수 있습니다

### Q2. API가 작동 안 될 때
1. Vercel 대시보드 → 프로젝트 → **"Logs"** 탭에서 에러 확인
2. Yahoo/CNN이 User-Agent를 차단했을 수 있음 → 코드 업데이트 필요
3. 대부분의 경우 하루 이틀 내에 복구됨

### Q3. 더 빠르게 만들고 싶어요
- Vercel은 기본적으로 Edge Network에 배포되어 이미 빠릅니다
- 5분 캐싱이 적용되어 있어 동일 종목 반복 조회는 거의 즉시 응답

### Q4. 혼자 쓰는 게 아니라 카페 전체에 공유해도 되나요?
✅ 됩니다. 단, Vercel Hobby 플랜 한도(월 100시간)는 **모든 사용자 합산**이니 주의.
→ 사용자가 많아지면 **Vercel Pro($20/월)** 또는 **캐싱 강화**로 해결

### Q5. 코드를 수정하려면?
GitHub에서 `api/quote-us.js` 등의 파일을 직접 수정 → 커밋 → Vercel이 자동으로 재배포합니다.

---

## 🆘 문제 해결

### "Function timeout" 에러
→ `vercel.json`의 `maxDuration`을 `10`에서 `30`으로 늘리기
(단 Hobby 플랜은 최대 10초까지만 가능)

### "CORS 에러"가 계산기에서 발생
→ `vercel.json`이 정상 업로드됐는지 확인
→ 브라우저 캐시 초기화 (Ctrl+Shift+R)

### Yahoo Finance 데이터가 안 옴
→ Yahoo가 User-Agent를 차단한 경우가 드물게 있음
→ `api/quote-us.js`의 User-Agent 문자열을 최신 크롬 버전으로 업데이트

---

## 📞 도움이 더 필요하면

- Vercel 공식 문서: https://vercel.com/docs
- Vercel 커뮤니티: https://github.com/vercel/vercel/discussions

성공적인 배포를 응원합니다! 🎯
