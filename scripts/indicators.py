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
# ─────────────────────────────────────────────────────────
# 5개 축 연속점수
# ─────────────────────────────────────────────────────────
#
# 규칙을 켜짐/꺼짐으로 세던 방식에는 두 가지 문제가 있었다.
#
#  1. 중복 가중 — RSI·스토캐스틱·CCI·Williams %R 은 전부 단기 오실레이터라
#     같이 켜지고 같이 꺼진다(스토캐 ↔ W%R 자카드 0.68). 같은 현상을 네 번
#     세면 그 하나가 사실상 4표를 갖는다.
#  2. 계단 — 신호 1개가 10점이라 0개(30%)와 1개(33%)가 50점과 60점에 뭉쳤다.
#     493종목 표본에서 절반 가까이가 50~69점 한 칸에 몰렸다.
#
# 그래서 성격이 겹치는 것끼리 묶어 축을 만들고, 각 축을 0~100 연속값으로 낸다.
# 축 안에서는 평균을 내므로 중복이 가중으로 이어지지 않는다.
#
#   축1 과매도 강도  RSI·스토캐스틱·CCI·Williams %R
#   축2 낙폭 심도    52주 고점 대비·이격도 20/60/120/200일
#   축3 자금 흐름    MFI·거래량비율·OBV 기울기
#   축4 추세 위험    ADX/DI·데드크로스·연속하락·60일 모멘텀   (감점)
#   축5 반등 조짐    MACD 히스토그램 전환·볼린저 %B 회복      (가점)
#
# 값이 클수록 '매수 우호'다. 축4만 반대로 클수록 위험하다.

def _map(v: Optional[float], pts) -> Optional[float]:
    """구간 선형보간. pts 는 (입력, 출력) 오름차순."""
    if v is None:
        return None
    if v <= pts[0][0]:
        return float(pts[0][1])
    if v >= pts[-1][0]:
        return float(pts[-1][1])
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 <= v <= x1:
            if x1 == x0:
                return float(y1)
            return y0 + (y1 - y0) * (v - x0) / (x1 - x0)
    return None


def _avg(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def axis_oversold(o: Dict):
    """단기 오실레이터 네 개의 평균. 넷이 서로 중복이라 합산이 아니라 평균이다."""
    parts = {
        "RSI(14)":       _map(o.get("rsi"),        [(0, 100), (30, 80), (50, 50), (70, 20), (100, 0)]),
        "스토캐스틱 %K":  _map(o.get("stoch_k"),    [(0, 100), (20, 80), (50, 50), (80, 20), (100, 0)]),
        "CCI(20)":       _map(o.get("cci"),        [(-250, 100), (-100, 80), (0, 50), (100, 20), (250, 0)]),
        "Williams %R":   _map(o.get("williams_r"), [(-100, 100), (-80, 80), (-50, 50), (-20, 20), (0, 0)]),
    }
    return _avg(parts.values()), parts


def axis_drawdown(o: Dict):
    """얼마나 깊이 눌렸나. 기간이 길수록 임계를 크게 잡는다."""
    parts = {
        "52주 고점 대비": _map(o.get("from_high"), [(-60, 100), (-40, 85), (-25, 65), (-10, 35), (0, 5)]),
        "20일선 이격":    _map(o.get("disp20"),    [(-20, 100), (-10, 80), (-3, 55), (3, 40), (10, 10)]),
        "60일선 이격":    _map(o.get("disp60"),    [(-30, 100), (-15, 80), (-5, 55), (5, 40), (15, 10)]),
        "120일선 이격":   _map(o.get("disp120"),   [(-40, 100), (-20, 80), (-7, 55), (7, 40), (20, 10)]),
        "200일선 이격":   _map(o.get("disp200"),   [(-50, 100), (-25, 80), (-10, 55), (10, 40), (25, 10)]),
    }
    return _avg(parts.values()), parts


def axis_flow(o: Dict):
    """
    자금이 들어오는지. 낙폭 구간에서 거래량이 터지면 투매(바닥 신호)로 본다.
    OBV 가 우상향이면 파는 사람보다 사는 사람이 많다는 뜻이라 가점.
    """
    parts = {
        "MFI(14)":    _map(o.get("mfi"),       [(0, 100), (20, 80), (50, 50), (80, 20), (100, 0)]),
        "거래량 비율": _map(o.get("vol_ratio"), [(0.3, 35), (1.0, 50), (2.0, 70), (3.5, 85), (6, 90)]),
        "OBV 기울기":  _map(o.get("obv_slope"), [(-40, 15), (-15, 35), (0, 50), (15, 68), (40, 85)]),
    }
    return _avg(parts.values()), parts


def axis_trend_risk(o: Dict):
    """
    떨어지는 칼날인가. 여기만 클수록 나쁘다.
    과매도 신호가 아무리 많아도 하락 추세가 살아 있으면 깎아야 한다.
    """
    parts = {}
    adx, pdi, ndi = o.get("adx"), o.get("di_plus"), o.get("di_minus")
    if adx is not None and pdi is not None and ndi is not None:
        # 추세가 강하면서(ADX 높음) 방향이 아래(DI- 우위)일 때만 위험하다.
        strength = _map(adx, [(10, 0), (20, 30), (25, 55), (35, 80), (50, 100)]) or 0
        parts["ADX / DI"] = strength if ndi > pdi else strength * 0.15
    c = o.get("cross")
    if c is not None:
        parts["50/200일선"] = {"dead_cross": 95, "dead": 70,
                               "golden_cross": 5, "golden": 20}.get(c, 50)
    ds = o.get("down_streak")
    if ds is not None:
        parts["연속 하락일"] = _map(float(ds), [(0, 25), (2, 40), (4, 60), (7, 80), (10, 95)])
    m60 = o.get("mom60")
    if m60 is not None:
        parts["60일 모멘텀"] = _map(m60, [(-40, 90), (-20, 70), (0, 45), (20, 25), (40, 10)])
    return _avg(parts.values()), parts


def axis_reversal(o: Dict):
    """돌아설 조짐. MACD 상향 전환과 볼린저 하단 회복이 핵심."""
    parts = {}
    turn, hist = o.get("macd_turn"), o.get("macd_hist")
    if turn == "up":
        parts["MACD 전환"] = 95
    elif turn == "down":
        parts["MACD 전환"] = 10
    elif hist is not None:
        parts["MACD 전환"] = 62 if hist > 0 else 38
    pb = o.get("boll_pb")
    if pb is not None:
        # 하단을 막 되밟고 올라오는 0~25% 구간이 가장 좋다.
        parts["볼린저 %B"] = _map(pb, [(-20, 60), (0, 85), (20, 75), (50, 50), (80, 25), (110, 15)])
    return _avg(parts.values()), parts


AXIS_LABEL = {
    "oversold": "과매도 강도",
    "drawdown": "낙폭 심도",
    "flow": "자금 흐름",
    "trend_risk": "추세 위험",
    "reversal": "반등 조짐",
}

# 앞 세 축이 본체, 추세 위험은 빼고 반등 조짐은 더한다.
AXIS_WEIGHT = {"oversold": 0.40, "drawdown": 0.35, "flow": 0.25}
RISK_WEIGHT = 0.28
REVERSAL_WEIGHT = 0.16


# 축을 평균 내면 값이 가운데로 몰린다(정규분포로의 회귀). 실제로 국내 493종목
# 표본에서 원점수가 23~84 사이에만 들어와 60점대 한 칸에 40%가 뭉쳤다.
# 9단계 등급을 쓰려면 이걸 펴야 한다.
#
# 아래 앵커는 그 표본의 분위수(2/10/25/50/75/90/98%)를 등급 전체에 고르게
# 배치하도록 잡은 것이다. 경험값이므로, 분포가 한쪽으로 치우치면
# scripts/calibrate_score.py 로 다시 뽑아 갱신한다.
SCORE_STRETCH = [(0, 0), (29, 5), (43, 18), (52, 35), (61, 55),
                 (67, 72), (72, 85), (78, 95), (100, 100)]


def stretch_score(raw: Optional[float]) -> Optional[int]:
    v = _map(raw, SCORE_STRETCH)
    return None if v is None else int(max(0, min(100, round(v))))


def compute_axes(o: Dict) -> Dict:
    raw_ax = {
        "oversold": axis_oversold(o),
        "drawdown": axis_drawdown(o),
        "flow": axis_flow(o),
        "trend_risk": axis_trend_risk(o),
        "reversal": axis_reversal(o),
    }
    ax = {k: v[0] for k, v in raw_ax.items()}
    # 각 축이 어떤 지표를 몇 점으로 환산해 썼는지. 화면에서 근거를 펼쳐 보여준다.
    parts = {k: {kk: round(vv, 1) for kk, vv in (v[1] or {}).items() if vv is not None}
             for k, v in raw_ax.items()}
    base_parts, wsum = 0.0, 0.0
    for k, w in AXIS_WEIGHT.items():
        if ax[k] is not None:
            base_parts += ax[k] * w
            wsum += w
    if wsum == 0:
        return {"axes": ax, "score": None}
    base = base_parts / wsum

    score = base
    if ax["trend_risk"] is not None:
        score -= (ax["trend_risk"] - 50) * RISK_WEIGHT
    if ax["reversal"] is not None:
        score += (ax["reversal"] - 50) * REVERSAL_WEIGHT

    raw = max(0, min(100, score))
    return {"axes": {k: (round(v, 1) if v is not None else None) for k, v in ax.items()},
            "parts": parts,
            "base": round(base, 1),
            "raw": round(raw, 1),
            "score": stretch_score(raw)}


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

    # 종목점수는 5개 축 연속점수에서 나온다.
    # 신호 목록(oversold/overbought)은 '왜 이 점수인지' 설명용으로만 남긴다.
    a = compute_axes(out)
    out["axes"] = a["axes"]
    out["axis_parts"] = a.get("parts")
    out["base_score"] = a.get("base")
    out["raw_score"] = a.get("raw")
    out["stock_score"] = a["score"] if a["score"] is not None else 50

    # 떨어지는 칼날 경고 — 화면 배지의 근거
    out["knife"] = bool(
        adx_v is not None and ndi is not None and pdi is not None
        and adx_v >= 25 and ndi > pdi
    )

    # ATR 기반 물타기 간격. 종목마다 흔들리는 폭이 다른데 일률적으로
    # -5%씩 담으면 변동성 큰 종목은 하루 만에 다 소진된다.
    # 일평균 변동폭의 1.5배를 한 칸으로 잡는다.
    if ap is not None and ap > 0:
        step = round(ap * 1.5, 1)
        out["dca_step_pct"] = step
        c = closes[-1]
        out["dca_levels"] = [round(c * (1 - step * i / 100), 4) for i in (1, 2, 3)]
    else:
        out["dca_step_pct"] = None
        out["dca_levels"] = None

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
    ax = res.get("axes") or {}
    for k in ("oversold", "drawdown", "flow", "trend_risk", "reversal"):
        v = ax.get(k)
        r["ax_" + k] = "" if v is None else v
    r["knife"] = 1 if res.get("knife") else 0
    r["raw_score"] = res.get("raw_score") or ""
    r["dca_step_pct"] = res.get("dca_step_pct") or ""
    # 축별 재료 기여도 — '이 지표가 어느 축에 몇 점으로 들어갔나'를 화면에서 펼쳐 보여준다.
    # CSV 는 DictWriter(extrasaction="ignore") 라 이 중첩 키를 무시하고,
    # 샤드 JSON 은 row 를 통째로 덤프하므로 여기에만 실린다.
    r["parts"] = res.get("axis_parts") or {}
    return r


CSV_COLUMNS = ["ticker", "name", "date", "close", "rsi", "sheet_rsi",
               "stoch_k_raw", "stoch_d", "sheet_stoch_k", "sheet_stoch_d",
               "macd", "macd_signal", "macd_hist", "macd_turn", "boll_up", "boll_low",
               "boll_pb", "boll_bw", "cci", "williams_r", "atr_pct", "mfi", "adx",
               "di_plus", "di_minus", "disp20", "disp60", "disp120", "disp200",
               "vol_ratio", "obv_slope", "cross", "high52", "low52", "from_high",
               "from_low", "mom20", "mom60", "down_streak", "oversold_n",
               "overbought_n", "stock_score", "oversold", "overbought",
               "ax_oversold", "ax_drawdown", "ax_flow", "ax_trend_risk",
               "ax_reversal", "knife", "dca_step_pct", "raw_score"]
