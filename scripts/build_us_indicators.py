# -*- coding: utf-8 -*-
"""
미국 전종목 보조지표 산출.

야후 chart API에서 1년치 일봉(OHLCV)을 받아 지표를 계산한다.
종목당 1요청이라 유니버스 전체면 13,000여 요청이지만,
실측 초당 20건 안팎이라 10~20분이면 끝난다. 429는 공용 브레이크로 흡수한다.

산출:
    data/indicators_us.csv     전체 평면 CSV (사람·시트용)
    data/us/{A..Z,0-9,_}.json  프론트가 필요한 조각만 받는 용도
    data/index_us.json         검색 자동완성용 경량 인덱스

환경변수:
    LIMIT     앞에서 N개만 (로컬 테스트용)
    WORKERS   동시 실행 수 (기본 10)
"""

import os
import sys
import json
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import indicators as I

# 이미 만들어 두고 매주 갱신되는 미국 티커 유니버스를 그대로 재사용한다.
UNIVERSE_URL = "https://ttokjaetv.github.io/portfolio-sheet-data/data/us_symbols.json"
UNIVERSE_CACHE = os.path.join(C.DATA, "universe_us.json")

CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
         "?interval=1d&range=1y")


def yahoo_symbol(t: str) -> str:
    """나스닥 표기(BRK.B)를 야후 표기(BRK-B)로."""
    return t.strip().upper().replace(".", "-")


def load_universe() -> list:
    try:
        d = C.get_json(UNIVERSE_URL, C.NAVER_HEADERS, timeout=60)
        tickers = sorted(d.keys()) if isinstance(d, dict) else sorted(d)
        C.write_json(UNIVERSE_CACHE, tickers)
        print(f"  유니버스 원격 로드: {len(tickers)}종목")
        return tickers
    except Exception as e:
        print(f"  원격 유니버스 실패({type(e).__name__}) → 캐시 사용")
        if os.path.exists(UNIVERSE_CACHE):
            return json.load(open(UNIVERSE_CACHE, encoding="utf-8"))
        raise SystemExit("유니버스를 구할 수 없다. 네트워크를 확인할 것.")


def parse_chart(d: dict):
    """야후 응답 → 일봉 리스트 + 종목명."""
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        return None, None
    r = res[0]
    meta = r.get("meta") or {}
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
    bars = []
    for i, t in enumerate(ts):
        try:
            cc = c[i]
            if cc is None:
                continue
            bars.append({
                "date": datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"),
                "o": o[i] if i < len(o) and o[i] is not None else cc,
                "h": h[i] if i < len(h) and h[i] is not None else cc,
                "l": l[i] if i < len(l) and l[i] is not None else cc,
                "c": cc,
                "v": v[i] if i < len(v) and v[i] is not None else 0,
            })
        except (IndexError, TypeError):
            continue
    name = meta.get("longName") or meta.get("shortName") or ""
    return bars, name


def main():
    C.ensure_data_dirs("us")
    throttle = C.Throttle()

    tickers = load_universe()
    limit = int(os.environ.get("LIMIT") or 0)
    if limit:
        tickers = tickers[:limit]
    workers = int(os.environ.get("WORKERS") or 10)
    print(f"미국 보조지표 산출 시작 — {len(tickers)}종목, 동시 {workers}")

    def one(t):
        sym = yahoo_symbol(t)
        try:
            d = C.get_json(CHART.format(sym=sym), C.YAHOO_HEADERS,
                           timeout=30, tries=4, throttle=throttle)
        except Exception:
            return None
        bars, name = parse_chart(d)
        if not bars or len(bars) < 30:
            return None
        res = I.compute_all(bars)
        if not res.get("ok"):
            return None
        return I.to_row(t.strip().upper(), name, res)

    rows = [r for r in C.run_pool(tickers, one, workers, "US", 500) if r]
    rows.sort(key=lambda r: r["ticker"])

    print(f"  429 발생 {throttle.hits}회")
    C.guard_ratio(len(rows), len(tickers), 0.5, "미국")

    C.write_csv(os.path.join(C.DATA, "indicators_us.csv"), I.CSV_COLUMNS, rows)
    counts = C.write_shards("us", rows)
    print(f"  샤드 {len(counts)}개")

    C.write_json(os.path.join(C.DATA, "index_us.json"),
                 [[r["ticker"], r["name"]] for r in rows])

    C.write_json(os.path.join(C.DATA, "meta_us.json"), {
        "updated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "count": len(rows),
        "universe": len(tickers),
        "asOf": rows[-1]["date"] if rows else None,
        "throttleHits": throttle.hits,
    }, compact=False)


if __name__ == "__main__":
    main()
