# 기계적 물타기 계산기 (water-calc)

시장 상황과 종목의 보조지표를 함께 보고, 물타기 강도를 9단계로 제시하는 도구.

- 배포 주소: `https://ttokjaetv.github.io/water-calc/` (Pages 설정 후)
- 로컬 폴더: `C:\Users\이상준\Desktop\Claude\Water Calc\`

---

## 무엇이 바뀌었나

예전에는 Vercel 서버리스 함수가 브라우저 대신 야후·네이버를 호출했다.
야후·CNN·네이버가 전부 CORS로 브라우저 직접 호출을 막기 때문이었다.

지금은 **GitHub Actions가 미리 계산해 정적 파일로 배포**하고, 브라우저는 읽기만 한다.
Vercel은 더 이상 쓰지 않는다.

| | 예전 | 지금 |
|---|---|---|
| 서버 | Vercel 서버리스 5개 | 없음 |
| 조회 가능 종목 | 요청할 때마다 야후 조회 | **전종목 미리 계산** (미국 13,171 / 국내 3,965) |
| 종목 보조지표 | RSI 하나 | **10개 규칙** |
| 배포 | Vercel CLI | GitHub Actions → Pages |
| 이력·롤백 | 없음 | git |

---

## 데이터가 어디서 오나

```
현재가·종목명·환율   ttokjaeTV/portfolio-sheet-data  (10분마다 갱신, 그쪽 레포가 관리)
보조지표             이 레포 data/us|kr/{첫글자}.json (일 1회, 전일 종가 기준)
매크로·버블          이 레포 data/macro.json, bubble.json (하루 4회)
```

시세를 직접 만들지 않는 이유는 `portfolio-sheet-data`가 이미 전종목 시세를
10분마다 만들고 있어서다. 같은 걸 두 번 만들 이유가 없고, 네이버에 부하도 두 배가 된다.

**주의**: 그래서 이 도구는 `portfolio-sheet-data`에 의존한다.
그쪽 Actions가 죽으면 여기 현재가도 멈춘다. 그때는 `ttokjae-portfolio-tool` 스킬의
"시세가 안 나온다는 신고를 받으면" 절차를 따른다.

---

## 구조

```
index.html                      계산기 본체 (단일 HTML)
scripts/
  indicators.py                 보조지표 계산 엔진 (의존성 없음)
  build_us_indicators.py        미국 전종목  → data/indicators_us.csv, data/us/*.json
  build_kr_indicators.py        국내 전종목  → data/indicators_kr.csv, data/kr/*.json
  build_macro.py                매크로·버블  → data/macro.json, data/bubble.json
  common.py                     HTTP 재시도·동시실행·확보율 가드
.github/workflows/build.yml     갱신 + Pages 배포
legacy/vercel-api/              옛 Vercel 함수 사본 (참고용, 미사용)
```

`data/`는 git에 커밋하지 않는다. Actions가 만들어 Pages 아티팩트로 바로 올린다.
매일 수 MB씩 커밋하면 1년이면 레포가 수 GB가 된다.
예외는 `data/manual.json` — 자동 수집이 안 되는 값을 손으로 채우는 파일이다.

---

## 보조지표 10개 규칙

종목점수는 아래 과매도 신호가 몇 개 켜졌는지로 정해진다.
기준을 바꾸려면 `scripts/indicators.py`의 `OVERSOLD_RULES` 한 곳만 고치면 된다.
화면 문구는 `index.html`의 `SIGNAL_LABEL`이 짝을 이룬다. **둘을 같이 고칠 것.**

| 신호 | 과매도 기준 |
|---|---|
| RSI(14) | 30 이하 |
| 스토캐스틱 %K·%D | 둘 다 20 이하 |
| MACD | 히스토그램 상향 전환 |
| 볼린저밴드 | 하단선 이탈 (%B ≤ 0) |
| CCI(20) | −100 이하 |
| Williams %R(14) | −80 이하 |
| MFI(14) | 20 이하 |
| 20일선 이격도 | −10% 이하 |
| 200일선 이격도 | −15% 이하 |
| 52주 고점 대비 | −25% 이하 |

이 밖에 ATR%·ADX/DI·밴드폭·거래량비율·OBV·골든/데드크로스·모멘텀·연속하락일도
함께 계산해 화면에 보여준다(점수에는 안 들어간다).
단 **ADX ≥ 25 이면서 DI−가 DI+보다 크면** 하락 추세가 살아 있다고 보고 종목점수를 8점 깎는다.
떨어지는 칼날을 신호 개수만으로 사라고 하면 안 되기 때문이다.

### 구글시트와 값이 다른 이유

기존 시트(`[공유용] 과매수 과매도 보조지표 계산기`)는 `GOOGLEFINANCE`로 **종가만**
가져온다. 고가·저가·거래량이 없어서 세 지표가 변형돼 있다.

| 지표 | 시트 | 여기 |
|---|---|---|
| RSI | 단순평균(Cutler) | **Wilder** — HTS·트레이딩뷰 표준 |
| 스토캐스틱 | 종가로 고·저 대용, Fast | **실제 고가·저가**, Slow |
| 볼린저 | 표본 표준편차(n−1) | 동일 |
| MACD | 표준 | 동일 |

TSLA 2026-09-04 기준 RSI가 시트 54.97 / 표준 50.93으로 갈린다. 둘 다 틀린 게 아니라
정의가 다르다. 혼란을 막으려고 **시트 호환값도 같이 산출해서**(`sheet_rsi`,
`sheet_stoch_k`, `sheet_stoch_d`) 지표 모달 하단에 함께 보여준다.
시트 값과 소수점까지 일치하는 것을 확인했다.

---

## 최초 설정 (한 번만)

1. GitHub에서 **`ttokjaeTV/water-calc`** 레포 생성 (Public 권장 — Actions 무제한)
   - 레포명은 반드시 영문. 한글이면 Pages URL이 인코딩돼 `fetch`가 깨진다.
2. GitHub Desktop에서 이 폴더를 추가하고 push
3. 레포 **Settings → Pages → Source** 를 **GitHub Actions** 로 설정
   (Deploy from a branch 아님)
4. **Actions 탭 → 데이터 갱신 및 배포 → Run workflow → mode: full** 로 첫 실행
   - 15~25분 걸린다. 전종목 일봉을 받아 지표를 계산한다.
5. Vercel 프로젝트 `ttokjae-api` 는 배포가 확인된 뒤 삭제

## 평소 운영

- 손댈 게 없다. 평일 한국시간 07:00 전체 갱신, 10:00·16:00·22:00 매크로 갱신.
- 지표 기준을 바꾸고 싶으면 `OVERSOLD_RULES` + `SIGNAL_LABEL` 수정 후 push.

## 로컬 실행

```bash
cd "C:\Users\이상준\Desktop\Claude\Water Calc"
LIMIT=60 python3 scripts/build_us_indicators.py    # LIMIT 없으면 전종목
LIMIT=60 python3 scripts/build_kr_indicators.py
python3 scripts/build_macro.py
python3 -m http.server 8000                        # http://localhost:8000
```

`file://` 로 열면 `fetch`가 막혀 데이터가 안 뜬다. 반드시 http 서버로 열 것.

---

## 알아둘 함정

**야후는 누적 호출로 429를 낸다.** 짧게 300종목 정도는 초당 20건으로 멀쩡하지만,
계속 두드리면 막힌다. `common.py`의 `Throttle`이 한 번 막히면 전체 워커를 함께
쉬게 한다. 개별 재시도만 하면 계속 벽에 부딪힌다.

**종목코드에 문자가 섞인다.** `0193M0`, `0220W0`, `BRK.B` 가 실재한다.
정규식은 `\d{6}` 이 아니라 `[0-9A-Z]{6}`. 야후는 `BRK-B`, 나스닥은 `BRK.B` 표기다.

**KIND 상장법인목록은 EUC-KR 이고 열 순서가 `회사명 | 시장 | 종목코드 | 업종`** 이다.
종목코드가 두 번째 열이 아니다.

**네이버 siseJson은 정식 JSON이 아니다.** 홑따옴표에 후행 콤마가 붙는다.

**multpl.com 값 셀에 `&#x2002;` 엔티티가 있다.** 먼저 지우지 않으면 `2002`를 값으로
읽는다. 실제로 Shiller CAPE가 2002.0으로 나온 적이 있어 범위 검증을 걸어뒀다.

**FRED는 환경에 따라 아예 닿지 않는다.** 버핏지수(GDP)·연준금리·10Y-2Y가 여기 의존한다.
막히면 장단기 금리차는 `10년물 − 13주`로 근사하고, 나머지는 `data/manual.json`에
손으로 채운다. `macro.json`의 `errors` 배열과 `yieldCurveSource`를 보면 무엇이
자동이고 무엇이 근사인지 알 수 있다. **근사치를 실측처럼 쓰지 말 것.**

**KRX는 2026년부터 전면 로그인제다.** 외국인 순매수·52주 신고가 비율은 자동 수집이
안 되어 `null`로 두고 화면에서 수기 입력을 받는다. 지어내지 않는다.

---

## 면책

본 도구는 세금·수수료를 제외한 단순 계산 도구입니다. 특정 종목의 매수·매도를
권유하지 않으며, 투자 판단과 그 결과의 책임은 본인에게 있습니다.
시세는 15~20분 지연될 수 있습니다.
