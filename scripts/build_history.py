# -*- coding: utf-8 -*-
"""
매크로 지표의 과거 시계열.

카드를 눌렀을 때 '지금이 역사적으로 어디쯤인가' 를 보여주기 위한 데이터다.
소스마다 줄 수 있는 기간이 달라서, 되는 만큼만 받고 못 받는 건 만들지 않는다.

  VIX        야후 ^VIX 5년 (약 1,250 거래일)            ✅
  CNN F&G    CNN 이 1년치(250일)만 준다                  ⚠ 1년
  VKOSPI     과거 시계열 소스가 없다                      ❌ 생략
             (야후·네이버·pykrx 에 없고, 인베스팅닷컴은 403)
  똑재 F&G   3개 재료로 역산                              ⚠ 재료 3/5

똑재 F&G 역산이 5개가 아니라 3개인 이유
  - VKOSPI: 위와 같은 이유로 과거값이 없다
  - 52주 신고가 비율: 과거 시점의 전종목 상태가 필요하다. 3,900종목 ×
    5년 일봉을 매일 재계산해야 해서 현실적이지 않다.
  그래서 화면에 '재료 3개 기준' 이라고 밝히고, 현재 카드값과 다를 수 있음을 알린다.

산출: data/history.json
"""

import os
import sys
import json
import datetime
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import indicators as I

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d&range={r}"

# 화면의 scoreMomentum / scoreVkospiFG / scoreKospiRsi / scoreForeign 과
# 같은 규칙이어야 한다. 둘을 같이 고칠 것.
def score_momentum(p):
    return None if p is None else (
        100 if p <= -10 else 85 if p <= -5 else 70 if p <= -2 else
        50 if p <= 2 else 30 if p <= 5 else 15 if p <= 10 else 0)


def score_kospi_rsi(r):
    return None if r is None else (
        100 if r < 30 else 80 if r < 40 else 60 if r < 50 else
        40 if r < 60 else 20 if r < 70 else 0)


def score_foreign(t):
    return None if t is None else (
        100 if t <= -5 else 85 if t <= -3 else 70 if t <= -1 else
        50 if t <= 1 else 30 if t <= 3 else 15 if t <= 5 else 0)


def yahoo_daily(symbol, rng="5y"):
    d = C.get_json(CHART.format(s=urllib.parse.quote(symbol), r=rng),
                   C.YAHOO_HEADERS, timeout=40, tries=4)
    r = d["chart"]["result"][0]
    ts = r.get("timestamp") or []
    cl = (r["indicators"]["quote"][0].get("close") or [])
    out = []
    for i, t in enumerate(ts):
        v = cl[i] if i < len(cl) else None
        if v is None:
            continue
        out.append((datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"),
                    round(float(v), 2)))
    return out


def thin(series, keep=700):
    """
    5년 일봉을 그대로 보내면 파일이 커진다. 화면 폭을 생각하면 700포인트면
    충분하다. 최근 구간은 촘촘히 남기려고 뒤에서부터 간격을 계산한다.
    """
    if len(series) <= keep:
        return series
    step = len(series) / keep
    idx = sorted({int(i * step) for i in range(keep)} | {len(series) - 1})
    return [series[i] for i in idx if i < len(series)]


def vix_history():
    return thin(yahoo_daily("^VIX", "5y"))


def cnn_history():
    """CNN 은 1년치(250 포인트)만 준다. 5년은 제공하지 않는다."""
    d = C.get_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                   {**C.YAHOO_HEADERS, "Referer": "https://www.cnn.com/"},
                   timeout=40, tries=3)
    h = (d.get("fear_and_greed_historical") or {}).get("data") or []
    out = []
    for p in h:
        try:
            ts = float(p["x"]) / 1000.0
            out.append((datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
                        round(float(p["y"]), 1)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def kospi_daily(years=5):
    """네이버 siseJson 으로 코스피 일봉. 모멘텀·RSI 역산의 재료다."""
    import re
    end = datetime.date.today()
    start = end - datetime.timedelta(days=365 * years + 200)   # 125일 이평 여유분
    f = lambda d: d.strftime("%Y%m%d")
    url = ("https://api.finance.naver.com/siseJson.naver?symbol=KOSPI"
           f"&requestType=1&startTime={f(start)}&endTime={f(end)}&timeframe=day")
    raw = C.http_get(url, C.NAVER_HEADERS, timeout=60, tries=3)
    t = raw.decode("utf-8", "replace").strip().replace("'", '"')
    t = re.sub(r",\s*]", "]", t)
    rows = json.loads(t)
    out = []
    for r in rows[1:]:
        try:
            ds = str(r[0])
            c = float(r[4])
            if c > 0:
                out.append((f"{ds[0:4]}-{ds[4:6]}-{ds[6:8]}", c))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def foreign_history(years=5):
    """
    외국인 순매수 5영업일 합계(조원)의 시계열. KRX 로그인이 필요하다.
    자격증명이 없으면 빈 dict 를 돌려주고, 그때는 재료 2개로 역산한다.
    """
    import krx_auth
    if not krx_auth.login(verbose=False):
        print("  외국인 순매수: KRX 로그인 불가 — 이 재료는 빼고 역산한다")
        return {}
    from pykrx import stock
    end = datetime.date.today()
    start = end - datetime.timedelta(days=365 * years + 30)
    f = lambda d: d.strftime("%Y%m%d")
    daily = {}
    for mkt in ("KOSPI", "KOSDAQ"):
        try:
            df = stock.get_market_trading_value_by_date(f(start), f(end), mkt, on="외국인")
            col = [c for c in df.columns if "외국인" in c]
            if not col:
                continue
            for d, v in df[col[0]].items():
                key = d.strftime("%Y-%m-%d")
                daily[key] = daily.get(key, 0.0) + float(v)
        except Exception as e:
            print(f"  외국인 순매수 {mkt} 실패: {type(e).__name__}")
    # 5영업일 이동합계(조원)
    keys = sorted(daily)
    out, win = {}, []
    for k in keys:
        win.append(daily[k])
        if len(win) > 5:
            win.pop(0)
        if len(win) == 5:
            out[k] = round(sum(win) / 1e12, 3)
    return out


def ttokjae_fg_history():
    """
    똑재 공포탐욕지수 역산.

    현재 카드는 재료 5개(모멘텀·VKOSPI·RSI·외국인·신고가비율)로 계산하지만,
    과거는 VKOSPI 와 신고가비율의 시계열을 구할 수 없어 3개로만 낸다.
    그래서 같은 날이라도 카드 숫자와 그래프 값이 다를 수 있다. 숨기지 않고
    화면에 '재료 3개 기준' 이라고 밝힌다.
    """
    kospi = kospi_daily(5)
    if len(kospi) < 200:
        raise ValueError("코스피 일봉 부족")
    closes = [c for _, c in kospi]
    dates = [d for d, _ in kospi]

    foreign = foreign_history(5)
    used = ["코스피 125일 이평 괴리", "코스피 14일 RSI"]
    if foreign:
        used.append("외국인 순매수(5일 합계)")

    out = []
    for i in range(125, len(closes)):
        window = closes[:i + 1]
        ma125 = sum(window[-125:]) / 125
        mom = (window[-1] - ma125) / ma125 * 100
        # RSI 는 최근 60개만 넣어도 Wilder 평활이 충분히 수렴한다
        rsi = I.rsi(window[-60:]) if len(window) >= 60 else None

        parts = [score_momentum(round(mom, 2)), score_kospi_rsi(rsi)]
        fv = foreign.get(dates[i])
        if fv is not None:
            parts.append(score_foreign(fv))
        parts = [p for p in parts if p is not None]
        if len(parts) < 2:
            continue
        # 화면과 동일: 공포점수 평균을 100에서 빼 '탐욕' 방향으로 뒤집는다
        out.append((dates[i], round(100 - sum(parts) / len(parts), 1)))

    return thin(out), used


def main():
    C.ensure_data_dirs()
    hist = {"updated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "series": {}, "notes": {}}

    try:
        s = vix_history()
        hist["series"]["vix"] = s
        hist["notes"]["vix"] = f"야후 ^VIX · {s[0][0]} ~ {s[-1][0]}"
        print(f"  VIX {len(s)}포인트")
    except Exception as e:
        print(f"  ! VIX 실패 {type(e).__name__}")

    try:
        s = cnn_history()
        if s:
            hist["series"]["cnn-fg"] = s
            hist["notes"]["cnn-fg"] = f"CNN 제공 범위가 1년이다 · {s[0][0]} ~ {s[-1][0]}"
            print(f"  CNN F&G {len(s)}포인트 (1년)")
    except Exception as e:
        print(f"  ! CNN F&G 실패 {type(e).__name__}")

    try:
        s, used = ttokjae_fg_history()
        hist["series"]["kospi-fg"] = s
        hist["notes"]["kospi-fg"] = (
            f"재료 {len(used)}개로 역산 ({' · '.join(used)}). "
            "VKOSPI 와 52주 신고가 비율은 과거 시계열이 없어 빠졌다. "
            "그래서 현재 카드 숫자와 다를 수 있다.")
        print(f"  똑재 F&G {len(s)}포인트 · 재료 {used}")
    except Exception as e:
        print(f"  ! 똑재 F&G 실패 {type(e).__name__}: {str(e)[:80]}")

    # VKOSPI 는 과거 시계열 소스가 없다. 없는 걸 만들지 않고 이유를 남긴다.
    hist["notes"]["vkospi"] = (
        "과거 시계열을 구할 수 있는 무료 소스가 없다. "
        "야후·네이버·pykrx 에 없고 인베스팅닷컴은 403으로 막힌다. "
        "CNBC 는 현재값만 준다.")

    C.write_json(os.path.join(C.DATA, "history.json"), hist)
    print(f"  시리즈 {len(hist['series'])}종")


if __name__ == "__main__":
    main()
