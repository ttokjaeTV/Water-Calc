# -*- coding: utf-8 -*-
"""
시장(매크로) 지표 + 버블 지표 수집.

원칙 하나: 한 소스가 죽어도 나머지는 살린다.
값이 없으면 null 로 남기고 errors 에 이유를 적는다. 절대 지어내지 않는다.

산출:
    data/macro.json    시장 레벨 지표
    data/bubble.json   버블 판정 지표
    data/manual.json   자동 수집 불가 항목 (사람이 채운다, 덮어쓰지 않음)
"""

import os
import re
import sys
import csv
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import indicators as I

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d&range={r}"

CNN_HEADERS = {**C.YAHOO_HEADERS, "Referer": "https://www.cnn.com/"}
CNBC_HEADERS = {**C.YAHOO_HEADERS, "Referer": "https://www.cnbc.com/"}

errors = []


def note(source, e):
    errors.append({"source": source, "error": f"{type(e).__name__}: {str(e)[:120]}"})
    print(f"  ! {source} 실패 — {type(e).__name__}: {str(e)[:100]}")


def yahoo_series(symbol, rng="1y"):
    """야후에서 일봉을 받아 (종가리스트, meta) 로."""
    import urllib.parse
    d = C.get_json(CHART.format(s=urllib.parse.quote(symbol), r=rng),
                   C.YAHOO_HEADERS, timeout=30, tries=4)
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    closes = [c for c in (q.get("close") or []) if c is not None]
    return closes, r.get("meta") or {}


def yahoo_last(symbol, rng="5d"):
    closes, meta = yahoo_series(symbol, rng)
    v = meta.get("regularMarketPrice")
    if v is None and closes:
        v = closes[-1]
    prev = meta.get("chartPreviousClose")
    return ({"value": round(float(v), 4), "prev": round(float(prev), 4) if prev else None}
            if v is not None else None)


# ─────────────────────────────────────────────────────────
# 시장 지표
# ─────────────────────────────────────────────────────────

def cnn_fear_greed():
    d = C.get_json("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                   CNN_HEADERS, timeout=30, tries=3)
    f = d.get("fear_and_greed") or {}
    if f.get("score") is None:
        raise ValueError("score 없음")
    return {"value": round(f["score"]), "rating": f.get("rating", ""),
            "prev": round(f.get("previous_close") or 0)}


def vkospi():
    d = C.get_json(
        "https://quote.cnbc.com/quote-html-webservice/quote.htm?partnerId=2"
        "&requestMethod=quick&exthrs=1&noform=1&fund=1&output=json&symbols=.KSVKOSPI",
        CNBC_HEADERS, timeout=30, tries=3)
    q = d["QuickQuoteResult"]["QuickQuote"]
    q = q[0] if isinstance(q, list) else q
    v = float(q["last"])
    # 값 범위 가드 — 응답 포맷이 바뀌면 엉뚱한 숫자가 들어온다.
    if not (5 < v < 200):
        raise ValueError(f"VKOSPI 범위 이상: {v}")
    prev = q.get("previous_day_closing")
    return {"value": round(v, 2),
            "prev": round(float(prev), 2) if prev else None}


def kospi_fg():
    """똑재 공포탐욕지수 재료 — KOSPI 125일 이평 괴리(모멘텀)와 14일 RSI."""
    closes, _ = yahoo_series("^KS11", "2y")
    if len(closes) < 130:
        raise ValueError("KOSPI 일봉 부족")
    ma125 = sum(closes[-125:]) / 125
    return {
        "momentum": round((closes[-1] - ma125) / ma125 * 100, 2),
        "rsi": round(I.rsi(closes) or 0, 2),
        "close": round(closes[-1], 2),
    }


def foreign_net_buy():
    """
    외국인 순매수 — 최근 5영업일 합계(조 원). 똑재 공포탐욕지수 네 번째 재료.

    KRX 정보데이터시스템은 2026년부터 전면 로그인제라 예전엔 수기 입력이었다.
    자격증명이 있으면 자동으로 받아온다. 없으면 None 을 돌려주고
    화면에서 수기 입력을 받는다 — 지어내지 않는다.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import krx_auth
    if not krx_auth.login():
        raise RuntimeError("KRX 로그인 불가 (자격증명 또는 pykrx 없음)")

    from pykrx import stock
    end = datetime.date.today()
    start = end - datetime.timedelta(days=20)
    f = lambda d: d.strftime("%Y%m%d")

    total, detail = 0.0, {}
    for mkt in ("KOSPI", "KOSDAQ"):
        df = stock.get_market_trading_value_by_date(f(start), f(end), mkt, on="외국인")
        col = [c for c in df.columns if "외국인" in c]
        if not col or df.empty:
            continue
        v = float(df[col[0]].tail(5).sum()) / 1e12   # 조 원
        detail[mkt] = round(v, 3)
        total += v
    if not detail:
        raise ValueError("외국인 순매수 응답 없음")
    return {"value": round(total, 2), "unit": "조원", "days": 5, "byMarket": detail}


def high_low_ratio():
    """
    52주 신고가 비율 — 똑재 공포탐욕지수 다섯 번째 재료.

    KRX 를 뒤질 필요가 없다. 이미 국내 전종목 보조지표를 만들면서
    52주 고점·저점 대비 위치를 다 계산해 뒀기 때문이다.
    CNN 공포탐욕지수의 '신고가·신저가' 항목과 같은 방식으로 센다.
    """
    path = os.path.join(C.DATA, "indicators_kr.csv")
    if not os.path.exists(path):
        raise FileNotFoundError("indicators_kr.csv 없음 — 국내 지표를 먼저 만들어야 한다")
    hi = lo = 0
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                if r["from_high"] and float(r["from_high"]) >= -2:
                    hi += 1
                if r["from_low"] and float(r["from_low"]) <= 2:
                    lo += 1
            except ValueError:
                continue
    if hi + lo == 0:
        raise ValueError("신고가·신저가 종목이 하나도 없다")
    return {"value": round(hi / (hi + lo) * 100, 1),
            "high": hi, "low": lo, "basis": "국내 전종목 52주 고·저 대비 ±2%"}


def credit_spread():
    """
    하이일드 신용 스프레드의 대용치.
    FRED 가 막히는 환경이 있어, 국채(TLT) 대비 하이일드(HYG) 상대강도로 대신한다.
    값이 떨어질수록 신용 경계가 커지는 방향이다.
    """
    hyg, _ = yahoo_series("HYG", "1y")
    lqd, _ = yahoo_series("LQD", "1y")
    if len(hyg) < 60 or len(lqd) < 60:
        raise ValueError("HYG/LQD 일봉 부족")
    ratio = [h / l for h, l in zip(hyg[-len(lqd):], lqd[-len(hyg):])] if len(hyg) == len(lqd) \
        else [hyg[-i] / lqd[-i] for i in range(1, min(len(hyg), len(lqd)) + 1)][::-1]
    cur = ratio[-1]
    avg60 = sum(ratio[-60:]) / 60
    return {"ratio": round(cur, 4),
            "vs60d": round((cur - avg60) / avg60 * 100, 2)}


# FRED 는 환경에 따라 아예 닿지 않는다(방화벽/allowlist). 선택 항목이므로
# 짧게 한 번만 두드리고 포기한다. 전체 수집을 붙잡고 있으면 안 된다.
FRED_TIMEOUT = int(os.environ.get("FRED_TIMEOUT") or 12)


def fred_csv(series_id):
    """FRED. 망에서 막히는 경우가 있어 실패해도 전체를 세우지 않는다."""
    raw = C.http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
                     C.YAHOO_HEADERS, timeout=FRED_TIMEOUT, tries=1)
    lines = [l for l in raw.decode("utf-8", "replace").splitlines() if l.strip()]
    for line in reversed(lines[1:]):
        parts = line.split(",")
        if len(parts) >= 2 and parts[1].strip() not in (".", ""):
            return {"date": parts[0].strip(), "value": float(parts[1])}
    raise ValueError("유효값 없음")


def build_macro():
    m = {"updated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"}

    for key, fn in [
        ("cnnFearGreed", cnn_fear_greed),
        ("vkospi", vkospi),
        ("kospiFG", kospi_fg),
        ("creditSpread", credit_spread),
        ("foreignNetBuy", foreign_net_buy),
        ("highLowRatio", high_low_ratio),
    ]:
        try:
            m[key] = fn()
        except Exception as e:
            m[key] = None
            note(key, e)

    # 야후 단일 시세로 끝나는 것들
    for key, sym, label in [
        ("vix", "^VIX", "VIX"),
        ("ust10y", "^TNX", "미 10년물"),
        ("ust13w", "^IRX", "미 13주"),
        ("ust30y", "^TYX", "미 30년물"),
        ("dxy", "DX-Y.NYB", "달러인덱스"),
        ("usdkrw", "KRW=X", "원달러"),
        ("sp500", "^GSPC", "S&P500"),
        ("nasdaq", "^IXIC", "나스닥"),
        ("kospi", "^KS11", "코스피"),
        ("kosdaq", "^KQ11", "코스닥"),
        ("gold", "GC=F", "금"),
        ("wti", "CL=F", "WTI"),
    ]:
        try:
            m[key] = yahoo_last(sym)
        except Exception as e:
            m[key] = None
            note(label, e)

    # 장단기 금리차 — FRED 가 되면 정확한 값, 안 되면 10년물-13주로 근사
    try:
        m["yieldCurve"] = fred_csv("T10Y2Y")
        m["yieldCurveSource"] = "FRED T10Y2Y"
    except Exception as e:
        note("FRED T10Y2Y", e)
        t10 = (m.get("ust10y") or {}).get("value")
        t13 = (m.get("ust13w") or {}).get("value")
        if t10 is not None and t13 is not None:
            m["yieldCurve"] = {"date": None, "value": round(t10 - t13, 3)}
            m["yieldCurveSource"] = "근사(10년물 - 13주). FRED 접근 불가"
        else:
            m["yieldCurve"] = None
            m["yieldCurveSource"] = None

    m["errors"] = errors[:]
    return m


# ─────────────────────────────────────────────────────────
# 버블 지표
# ─────────────────────────────────────────────────────────

def multpl(path, lo=None, hi=None):
    """
    multpl.com 표의 최신 행 하나.

    값 셀에 &#x2002;(엔 스페이스) 엔티티가 들어 있어서, 엔티티를 먼저 지우지 않으면
    '2002' 를 값으로 잘못 읽는다. 실제로 그렇게 CAPE=2002.0 이 나왔었다.
    파싱이 어긋나도 조용히 넘어가지 않도록 범위 검증을 함께 건다.
    """
    h = C.http_get(f"https://www.multpl.com/{path}", C.YAHOO_HEADERS,
                   timeout=45, tries=3).decode("utf-8", "replace")
    i = h.find('<table id="datatable"')
    if i < 0:
        raise ValueError("표를 못 찾음")
    body = re.sub(r"&#x[0-9a-fA-F]+;|&#\d+;|&nbsp;", " ", h[i:i + 4000])
    m = re.search(r"<td>\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4})\s*</td>\s*"
                  r"<td>\s*(-?[\d.,]+)\s*</td>", body)
    if not m:
        raise ValueError("행 패턴 불일치")
    val = float(m.group(2).replace(",", ""))
    if (lo is not None and val < lo) or (hi is not None and val > hi):
        raise ValueError(f"값이 예상 범위를 벗어남: {val} (허용 {lo}~{hi}) — 파싱 확인 필요")
    return {"date": m.group(1).strip(), "value": val}


def buffett_indicator():
    """버핏지수 = 미국 전체 시가총액(Wilshire 5000) / 명목 GDP × 100."""
    w, _ = yahoo_series("^FTW5000", "5d")   # yahoo_series 안에서 인코딩한다
    if not w:
        raise ValueError("Wilshire 시세 없음")
    gdp = fred_csv("GDP")          # 10억 달러 단위, 분기
    # Wilshire 5000 지수는 대략 시가총액(10억 달러)과 같은 스케일로 쓰인다.
    return {"wilshire": round(w[-1], 2),
            "gdp": gdp["value"], "gdpDate": gdp["date"],
            "value": round(w[-1] / gdp["value"] * 100, 1)}


def ma200_gap(symbol="SPY"):
    closes, _ = yahoo_series(symbol, "2y")
    if len(closes) < 200:
        raise ValueError("200일 데이터 부족")
    ma = sum(closes[-200:]) / 200
    return {"symbol": symbol, "close": round(closes[-1], 2),
            "ma200": round(ma, 2),
            "value": round((closes[-1] - ma) / ma * 100, 2)}


def build_bubble():
    b = {"updated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"}
    for key, fn, label in [
        # 범위는 '역사적으로 이 밖이면 파싱이 틀린 것' 수준으로 넉넉히 잡았다.
        ("shillerCAPE", lambda: multpl("shiller-pe/table/by-month", 5, 70), "Shiller CAPE"),
        ("sp500EPS", lambda: multpl("s-p-500-earnings/table/by-quarter", 10, 500), "S&P500 EPS"),
        ("buffett", buffett_indicator, "버핏지수"),
        ("ma200Gap", ma200_gap, "200일선 괴리"),
        ("fedFunds", lambda: fred_csv("DFF"), "연준 정책금리"),
    ]:
        try:
            b[key] = fn()
        except Exception as e:
            b[key] = None
            note(label, e)
    b["errors"] = [e for e in errors]
    return b


def main():
    C.ensure_data_dirs()
    print("매크로 지표 수집")
    macro = build_macro()
    print("버블 지표 수집")
    bubble = build_bubble()

    # 수기 입력 파일은 있으면 건드리지 않는다.
    mp = os.path.join(C.DATA, "manual.json")
    if not os.path.exists(mp):
        C.write_json(mp, {
            "_설명": "자동 수집이 안 되는 값을 손으로 채운다. Actions 가 덮어쓰지 않는다.",
            "buffettIndicator": None,
            "shillerCAPE": None,
            "foreignNetBuy": None,
            "highLowRatio": None,
            "updatedBy": None,
            "updatedAt": None,
        }, compact=False)

    C.write_json(os.path.join(C.DATA, "macro.json"), macro, compact=False)
    C.write_json(os.path.join(C.DATA, "bubble.json"), bubble, compact=False)

    got = sum(1 for k, v in macro.items()
              if k not in ("updated", "errors", "yieldCurveSource") and v)
    print(f"  매크로 확보 {got}개 / 오류 {len(macro.get('errors') or [])}건")
    if got < 4:
        raise SystemExit("매크로 확보 4개 미만 — 배포 중단")


if __name__ == "__main__":
    main()
