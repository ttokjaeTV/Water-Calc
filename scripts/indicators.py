# -*- coding: utf-8 -*-
"""
보조지표 계산 엔진 (의존성 없음, 순수 파이썬)

입력은 과거→최신 순으로 정렬된 일봉 리스트.
    bars = [{"date":"20260904","o":..,"h":..,"l":..,"c":..,"v":..}, ...]

모든 함수는 '가장 최근 시점의 값' 하나를 돌려준다.
데이터가 모자라면 None. 절대 예외를 던지지 않는다 —
전종목 배치에서 한 종목 때문에 파이프라인이 죽으면 안 되기 때문이다.

구글시트 '[공유용] 과매수 과매도 보조지표 계산기'의 4개 지표
(RSI / 스토캐스틱 / MACD / 볼린저밴드)와 정의를 일치시켰다.
"""

from typing import List, Dict, Optional, Sequence

Bar = Dict[str, float]


# ─────────────────────────────────────────────────────────
# 기본 도구
# ─────────────────────────────────────────────────────────

def _sma(vals: Sequence[float], n: int) -> Optional[float]:
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _sma_series(vals: Sequence[float], n: int) -> List[Optional[float]]:
    out, run = [], 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= n:
            run -= vals[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def _ema_series(vals: Sequence[float], n: int) -> List[Optional[float]]:
    """첫 EMA는 앞 n개의 단순평균으로 시드한다 (일반적인 차트 툴 관행)."""
    if len(vals) < n:
        return [None] * len(vals)
    k = 2.0 / (n + 1)
    out: List[Optional[float]] = [None] * (n - 1)
    ema = sum(vals[:n]) / n
    out.append(ema)
    for v in vals[n:]:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _stdev(vals: Sequence[float], sample: bool = True) -> float:
    """
    기본은 표본 표준편차(n-1).
    구글시트 STDEV와 국내 HTS 볼린저밴드가 이 방식이라 시트와 값이 일치한다.
    (트레이딩뷰 등 일부는 모집단(n)을 쓴다 — sample=False)
    """
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    d = (n - 1) if sample else n
    return (sum((v - m) ** 2 for v in vals) / d) ** 0.5


def _wilder_smooth(vals: Sequence[float], n: int) -> List[Optional[float]]:
    """Wilder 평활 (RSI·ATR·ADX 공용)."""
    if len(vals) < n:
        return [None] * len(vals)
    out: List[Optional[float]] = [None] * (n - 1)
    acc = sum(vals[:n]) / n
    out.append(acc)
    for v in vals[n:]:
        acc = (acc * (n - 1) + v) / n
        out.append(acc)
    return out


def _r(v: Optional[float], nd: int = 2) -> Optional[float]:
    if v is None:
        return None
    try:
        if v != v or v in (float("inf"), float("-inf")):  # NaN/Inf 방어
            return None
        return round(float(v), nd)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# 개별 지표
# ─────────────────────────────────────────────────────────

def _gains_losses(closes: Sequence[float]):
    g, l = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        g.append(ch if ch > 0 else 0.0)
        l.append(-ch if ch < 0 else 0.0)
    return g, l


def rsi(closes: Sequence[float], n: int = 14) -> Optional[float]:
    """Wilder RSI — HTS·트레이딩뷰·야후가 쓰는 표준 방식."""
    if len(closes) < n + 1:
        return None
    g, l = _gains_losses(closes)
    ag, al = _wilder_smooth(g, n)[-1], _wilder_smooth(l, n)[-1]
    if ag is None or al is None:
        return None
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def rsi_cutler(closes: Sequence[float], n: int = 14) -> Optional[float]:
    """
    단순이동평균 기반 RSI(Cutler's RSI).
    구글시트 '보조지표 계산기'가 쓰는 방식이라, 시트와 대조하려고 함께 낸다.
    같은 종목이라도 Wilder 방식과 3~5포인트 차이가 난다.
    """
    if len(closes) < n + 1:
        return None
    g, l = _gains_losses(closes)
    ag, al = sum(g[-n:]) / n, sum(l[-n:]) / n
    if al == 0:
        return 100.0 if ag > 0 else None
    return 100.0 - (100.0 / (1.0 + ag / al))


def _stoch_raw(bars: List[Bar], n: int, use_hl: bool) -> List[float]:
    """Fast %K 시계열. use_hl=False면 고·저 대신 종가로 최고/최저를 잡는다."""
    out = []
    for i in range(n - 1, len(bars)):
        w = bars[i - n + 1:i + 1]
        if use_hl:
            hi, lo = max(b["h"] for b in w), min(b["l"] for b in w)
        else:
            hi, lo = max(b["c"] for b in w), min(b["c"] for b in w)
        rng = hi - lo
        out.append(50.0 if rng == 0 else (bars[i]["c"] - lo) / rng * 100.0)
    return out


def stochastic(bars: List[Bar], n: int = 14, d: int = 3, slowing: int = 3):
    """
    Slow Stochastic (고가·저가 기반) — HTS 기본값.
    Fast %K = (종가 - N일 최저)/(N일 최고 - N일 최저) × 100
    Slow %K = Fast %K 의 slowing일 평균,  %D = Slow %K 의 d일 평균
    """
    if len(bars) < n + slowing + d:
        return None, None
    fast = _stoch_raw(bars, n, use_hl=True)
    kv = [x for x in _sma_series(fast, slowing) if x is not None]
    if len(kv) < d:
        return None, None
    return kv[-1], _sma(kv, d)


def stochastic_sheet(bars: List[Bar], n: int = 14, d: int = 3):
    """
    구글시트 호환 스토캐스틱: Fast %K/%D 이고, 고·저 대신 '종가'만 쓴다.
    시트가 GOOGLEFINANCE로 종가만 받아오기 때문에 생긴 형태다.
    검증 결과 시트 값과 소수점까지 일치한다.
    """
    if len(bars) < n + d:
        return None, None
    fast = _stoch_raw(bars, n, use_hl=False)
    if len(fast) < d:
        return None, None
    return fast[-1], _sma(fast, d)


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, sig: int = 9):
    """MACD선, 시그널선, 히스토그램, 그리고 직전 히스토그램(교차 판정용)."""
    if len(closes) < slow + sig:
        return None, None, None, None
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    line = [(a - b) if (a is not None and b is not None) else None
            for a, b in zip(ef, es)]
    lv = [x for x in line if x is not None]
    if len(lv) < sig + 1:
        return None, None, None, None
    sg = _ema_series(lv, sig)
    hist = [(a - b) if b is not None else None for a, b in zip(lv, sg)]
    hv = [x for x in hist if x is not None]
    if not hv:
        return None, None, None, None
    prev = hv[-2] if len(hv) >= 2 else None
    return lv[-1], sg[-1], hv[-1], prev


def bollinger(closes: Sequence[float], n: int = 20, k: float = 2.0):
    """중심선·상단·하단·%B·밴드폭."""
    if len(closes) < n:
        return (None,) * 5
    w = closes[-n:]
    mid = sum(w) / n
    sd = _stdev(w)
    up, lo = mid + k * sd, mid - k * sd
    rng = up - lo
    pb = None if rng == 0 else (closes[-1] - lo) / rng * 100.0
    bw = None if mid == 0 else rng / mid * 100.0
    return mid, up, lo, pb, bw


def cci(bars: List[Bar], n: int = 20) -> Optional[float]:
    if len(bars) < n:
        return None
    tp = [(b["h"] + b["l"] + b["c"]) / 3.0 for b in bars]
    w = tp[-n:]
    m = sum(w) / n
    md = sum(abs(v - m) for v in w) / n
    if md == 0:
        return 0.0
    return (tp[-1] - m) / (0.015 * md)


def williams_r(bars: List[Bar], n: int = 14) -> Optional[float]:
    if len(bars) < n:
        return None
    w = bars[-n:]
    hi = max(b["h"] for b in w)
    lo = min(b["l"] for b in w)
    if hi == lo:
        return -50.0
    return (hi - bars[-1]["c"]) / (hi - lo) * -100.0


def _true_ranges(bars: List[Bar]) -> List[float]:
    tr = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return tr


def atr(bars: List[Bar], n: int = 14):
    """ATR과 ATR%(종가 대비). 물타기 간격 산정에 쓰려고 %도 같이 낸다."""
    if len(bars) < n + 1:
        return None, None
    a = _wilder_smooth(_true_ranges(bars), n)[-1]
    if a is None:
        return None, None
    c = bars[-1]["c"]
    return a, (a / c * 100.0 if c else None)


def mfi(bars: List[Bar], n: int = 14) -> Optional[float]:
    """거래량 가중 RSI. 거래량이 0인 종목은 None."""
    if len(bars) < n + 1:
        return None
    tp = [(b["h"] + b["l"] + b["c"]) / 3.0 for b in bars]
    pos = neg = 0.0
    for i in range(len(bars) - n, len(bars)):
        flow = tp[i] * (bars[i].get("v") or 0)
        if tp[i] > tp[i - 1]:
            pos += flow
        elif tp[i] < tp[i - 1]:
            neg += flow
    if pos + neg == 0:
        return None
    if neg == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + pos / neg))


def adx(bars: List[Bar], n: int = 14):
    """ADX(추세 강도) + DI+/DI-. 하락추세가 살아있는지 거르는 필터로 쓴다."""
    if len(bars) < 2 * n + 1:
        return None, None, None
    pdm, ndm = [], []
    for i in range(1, len(bars)):
        up = bars[i]["h"] - bars[i - 1]["h"]
        dn = bars[i - 1]["l"] - bars[i]["l"]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        ndm.append(dn if (dn > up and dn > 0) else 0.0)
    tr_s = _wilder_smooth(_true_ranges(bars), n)
    p_s = _wilder_smooth(pdm, n)
    n_s = _wilder_smooth(ndm, n)
    dx = []
    for t, p, m in zip(tr_s, p_s, n_s):
        if t is None or p is None or m is None or t == 0:
            continue
        pdi, ndi = p / t * 100.0, m / t * 100.0
        s = pdi + ndi
        dx.append(0.0 if s == 0 else abs(pdi - ndi) / s * 100.0)
    if len(dx) < n:
        return None, None, None
    adx_v = _wilder_smooth(dx, n)[-1]
    t, p, m = tr_s[-1], p_s[-1], n_s[-1]
    if not t:
        return adx_v, None, None
    return adx_v, p / t * 100.0, m / t * 100.0


def disparity(closes: Sequence[float], n: int) -> Optional[float]:
    """이격도: 현재가가 N일 이동평균 대비 몇 % 위/아래인가."""
    ma = _sma(closes, n)
    if ma is None or ma == 0:
        return None
    return (closes[-1] - ma) / ma * 100.0


def volume_ratio(bars: List[Bar], n: int = 20) -> Optional[float]:
    """오늘 거래량 / 최근 N일 평균 거래량. 1.0이 평소 수준."""
    if len(bars) < n:
        return None
    vs = [(b.get("v") or 0) for b in bars[-n:]]
    avg = sum(vs) / n
    if avg == 0:
        return None
    return (bars[-1].get("v") or 0) / avg


def obv_slope(bars: List[Bar], n: int = 20) -> Optional[float]:
    """OBV의 최근 N일 변화율(%). 값 자체보다 방향이 의미 있어 기울기로 낸다."""
    if len(bars) < n + 1:
        return None
    o = 0.0
    series = [0.0]
    for i in range(1, len(bars)):
        v = bars[i].get("v") or 0
        if bars[i]["c"] > bars[i - 1]["c"]:
            o += v
        elif bars[i]["c"] < bars[i - 1]["c"]:
            o -= v
        series.append(o)
    base = abs(series[-n - 1])
    if base == 0:
        return None
    return (series[-1] - series[-n - 1]) / base * 100.0


def cross_50_200(closes: Sequence[float]) -> Optional[str]:
    """골든크로스/데드크로스 상태와 최근 전환 여부."""
    if len(closes) < 201:
        return None
    m50, m200 = _sma_series(closes, 50), _sma_series(closes, 200)
    if m50[-1] is None or m200[-1] is None:
        return None
    now = "golden" if m50[-1] > m200[-1] else "dead"
    if m50[-2] is not None and m200[-2] is not None:
        was = "golden" if m50[-2] > m200[-2] else "dead"
        if was != now:
            return now + "_cross"   # 오늘 막 전환
    return now


def high_low_52w(bars: List[Bar]):
    """52주 고·저와 각각으로부터의 괴리율."""
    w = bars[-252:] if len(bars) >= 252 else bars
    if not w:
        return (None,) * 4
    hi = max(b["h"] for b in w)
    lo = min(b["l"] for b in w)
    c = bars[-1]["c"]
    return (hi, lo,
            (c - hi) / hi * 100.0 if hi else None,
            (c - lo) / lo * 100.0 if lo else None)


def momentum(closes: Sequence[float], n: int) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    base = closes[-n - 1]
    if base == 0:
        return None
    return (closes[-1] - base) / base * 100.0


def down_streak(closes: Sequence[float]) -> int:
    """연속 하락일수. 물타기 타이밍 체감에 직접 쓰인다."""
    s = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]:
            s += 1
        else:
            break
    return s


# ─────────────────────────────────────────────────────────
# 종합
# ─────────────────────────────────────────────────────────

# 과매도(=매수 우호) 신호 판정 기준. UI의 설명 문구와 이 표가 유일한 출처다.
OVERSOLD_RULES = {
    "rsi":        ("rsi",        "<=", 30,   "RSI 30 이하"),
    "stoch":      ("stoch_k",    "<=", 20,   "%K·%D 모두 20 이하"),
    "macd":       ("macd_turn",  "==", "up", "MACD 히스토그램 상향 전환"),
    "boll":       ("boll_pb",    "<=", 0,    "볼린저 하단선 이탈"),
    "cci":        ("cci",        "<=", -100, "CCI -100 이하"),
    "williams":   ("williams_r", "<=", -80,  "Williams %R -80 이하"),
    "mfi":        ("mfi",        "<=", 20,   "MFI 20 이하"),
    "disp20":     ("disp20",     "<=", -10,  "20일선 -10% 이격"),
    "disp200":    ("disp200",    "<=", -15,  "200일선 -15% 이격"),
    "from_high":  ("from_high",  "<=", -25,  "52주 고점 대비 -25%"),
}

OVERBOUGHT_RULES = {
    "rsi":       ("rsi",        ">=", 70,     "RSI 70 이상"),
    "stoch":     ("stoch_k",    ">=", 80,     "%K·%D 모두 80 이상"),
    "macd":      ("macd_turn",  "==", "down", "MACD 히스토그램 하향 전환"),
    "boll":      ("boll_pb",    ">=", 100,    "볼린저 상단선 돌파"),
    "cci":       ("cci",        ">=", 100,    "CCI 100 이상"),
    "williams":  ("williams_r", ">=", -20,    "Williams %R -20 이상"),
    "mfi":       ("mfi",        ">=", 80,     "MFI 80 이상"),
    "disp20":    ("disp20",     ">=", 10,     "20일선 +10% 이격"),
    "disp200":   ("disp200",    ">=", 20,     "200일선 +20% 이격"),
    "from_high": ("from_high",  ">=", -2,     "52주 고점 근접"),
}


def _passes(val, op, thr) -> bool:
    if val is None:
        return False
    if op == "<=":
        return val <= thr
    if op == ">=":
        return val >= thr
    if op == "==":
        return val == thr
    return False


def compute_all(bars: List[Bar]) -> Dict:
    """
    일봉 리스트 하나를 받아 전체 보조지표 + 신호 집계를 낸다.
    스토캐스틱은 시트와 동일하게 %K·%D가 '모두' 조건을 만족해야 신호로 친다.
    """
    bars = [b for b in bars if b.get("c")]
    out: Dict = {"bars": len(bars)}
    if len(bars) < 30:
        out["ok"] = False
        return out

    closes = [b["c"] for b in bars]

    k, d = stochastic(bars)
    ml, ms, mh, mh_prev = macd(closes)
    bmid, bup, blo, bpb, bbw = bollinger(closes)
    a, ap = atr(bars)
    adx_v, pdi, ndi = adx(bars)
    hi52, lo52, from_hi, from_lo = high_low_52w(bars)

    # MACD 교차: 히스토그램 부호 전환만 신호로 인정한다.
    macd_turn = None
    if mh is not None and mh_prev is not None:
        if mh_prev <= 0 < mh:
            macd_turn = "up"
        elif mh_prev >= 0 > mh:
            macd_turn = "down"

    # 스토캐스틱은 %K·%D 동시 조건이라 대표값을 따로 만든다.
    stoch_k = None
    if k is not None and d is not None:
        stoch_k = max(k, d) if (k <= 20 and d <= 20) else (
            min(k, d) if (k >= 80 and d >= 80) else (k + d) / 2)

    # 구글시트 호환값 — 시트와 대조할 때만 쓴다 (판정에는 표준값을 쓴다)
    sk_sheet, sd_sheet = stochastic_sheet(bars)

    out.update({
        "ok": True,
        "date": bars[-1].get("date"),
        "close": _r(closes[-1], 4),
        "rsi": _r(rsi(closes)),
        "sheet_rsi": _r(rsi_cutler(closes)),
        "sheet_stoch_k": _r(sk_sheet), "sheet_stoch_d": _r(sd_sheet),
        "stoch_k": _r(stoch_k), "stoch_k_raw": _r(k), "stoch_d": _r(d),
        "macd": _r(ml, 4), "macd_signal": _r(ms, 4), "macd_hist": _r(mh, 4),
        "macd_turn": macd_turn,
        "boll_mid": _r(bmid, 4), "boll_up": _r(bup, 4), "boll_low": _r(blo, 4),
        "boll_pb": _r(bpb), "boll_bw": _r(bbw),
        "cci": _r(cci(bars)),
        "williams_r": _r(williams_r(bars)),
        "atr": _r(a, 4), "atr_pct": _r(ap),
        "mfi": _r(mfi(bars)),
        "adx": _r(adx_v), "di_plus": _r(pdi), "di_minus": _r(ndi),
        "disp20": _r(disparity(closes, 20)),
        "disp60": _r(disparity(closes, 60)),
        "disp120": _r(disparity(closes, 120)),
        "disp200": _r(disparity(closes, 200)),
        "vol_ratio": _r(volume_ratio(bars)),
        "obv_slope": _r(obv_slope(bars)),
        "cross": cross_50_200(closes),
        "high52": _r(hi52, 4), "low52": _r(lo52, 4),
        "from_high": _r(from_hi), "from_low": _r(from_lo),
        "mom20": _r(momentum(closes, 20)),
        "mom60": _r(momentum(closes, 60)),
        "down_streak": down_streak(closes),
    })

    os_hits = [name for name, (f, op, thr, _) in OVERSOLD_RULES.items()
               if _passes(out.get(f), op, thr)]
    ob_hits = [name for name, (f, op, thr, _) in OVERBOUGHT_RULES.items()
               if _passes(out.get(f), op, thr)]

    out["oversold"] = os_hits
    out["overbought"] = ob_hits
    out["oversold_n"] = len(os_hits)
    out["overbought_n"] = len(ob_hits)
    out["rule_total"] = len(OVERSOLD_RULES)

    # 종목점수 0~100. 과매도 신호가 많을수록 높다(= 매수 우호).
    # 과매수 신호는 감점. ADX가 높은 하락추세(DI- 우위)는 '떨어지는 칼날'이라 감점한다.
    score = 50.0 + (len(os_hits) - len(ob_hits)) * (50.0 / len(OVERSOLD_RULES)) * 2
    if adx_v is not None and ndi is not None and pdi is not None:
        if adx_v >= 25 and ndi > pdi:
            score -= 8
    out["stock_score"] = int(max(0, min(100, round(score))))
    return out


def to_row(sym: str, name: str, res: Dict) -> Dict:
    """CSV 한 줄로 납작하게 만든다."""
    r = {"ticker": sym, "name": name}
    for kk in ("date", "close", "rsi", "sheet_rsi", "stoch_k_raw", "stoch_d",
               "sheet_stoch_k", "sheet_stoch_d", "macd", "macd_signal",
               "macd_hist", "macd_turn", "boll_up", "boll_low", "boll_pb", "boll_bw",
               "cci", "williams_r", "atr_pct", "mfi", "adx", "di_plus", "di_minus",
               "disp20", "disp60", "disp120", "disp200", "vol_ratio", "obv_slope",
               "cross", "high52", "low52", "from_high", "from_low", "mom20", "mom60",
               "down_streak", "oversold_n", "overbought_n", "stock_score"):
        v = res.get(kk)
        r[kk] = "" if v is None else v
    r["oversold"] = "|".join(res.get("oversold") or [])
    r["overbought"] = "|".join(res.get("overbought") or [])
    return r


CSV_COLUMNS = ["ticker", "name", "date", "close", "rsi", "sheet_rsi",
               "stoch_k_raw", "stoch_d", "sheet_stoch_k", "sheet_stoch_d",
               "macd", "macd_signal", "macd_hist", "macd_turn", "boll_up", "boll_low",
               "boll_pb", "boll_bw", "cci", "williams_r", "atr_pct", "mfi", "adx",
               "di_plus", "di_minus", "disp20", "disp60", "disp120", "disp200",
               "vol_ratio", "obv_slope", "cross", "high52", "low52", "from_high",
               "from_low", "mom20", "mom60", "down_streak", "oversold_n",
               "overbought_n", "stock_score", "oversold", "overbought"]
