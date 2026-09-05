# -*- coding: utf-8 -*-
"""
국내 전종목(ETF + 개별주식) 보조지표 산출.

네이버 siseJson 이 일봉을 OHLCV + 외국인소진율까지 준다.
    ['날짜','시가','고가','저가','종가','거래량','외국인소진율']

유니버스
    ETF      : ttokjaeTV/etf-selector 의 krx_etf_master.json (약 1,160)
    개별주식  : KIND 상장법인목록 (EUC-KR, 인증 불필요, 약 2,700)

산출:
    data/indicators_kr.csv
    data/kr/{0..9,A..Z}.json
    data/index_kr.json
"""

import os
import sys
import re
import json
import io
import csv
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import indicators as I

ETF_MASTER = "https://ttokjaetv.github.io/etf-selector/data/krx_etf_master.json"
KIND = ("https://kind.krx.co.kr/corpgeneral/corpList.do"
        "?method=download&searchType=13")
SISE = ("https://api.finance.naver.com/siseJson.naver?symbol={code}"
        "&requestType=1&startTime={s}&endTime={e}&timeframe=day")

UNIVERSE_CACHE = os.path.join(C.DATA, "universe_kr.json")


def load_etfs():
    try:
        d = C.get_json(ETF_MASTER, C.NAVER_HEADERS, timeout=60)
        items = d.get("etfs") if isinstance(d, dict) else d
        out = []
        for e in items or []:
            code = (e.get("ticker") or e.get("code") or e.get("shortCode") or "").strip()
            name = (e.get("name") or "").strip()
            # 종목코드에 문자가 섞인다 (0193M0, 0220W0). \d{6} 을 쓰면 안 된다.
            if re.fullmatch(r"[0-9A-Z]{6}", code):
                out.append((code, name, "ETF"))
        print(f"  ETF 유니버스: {len(out)}종목")
        return out
    except Exception as e:
        print(f"  ETF 마스터 실패: {type(e).__name__} {e}")
        return []


def load_stocks():
    """KIND 상장법인목록은 EUC-KR HTML 표다."""
    try:
        raw = C.http_get(KIND, C.NAVER_HEADERS, timeout=90)
        html = raw.decode("euc-kr", "replace")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
        out = []
        # 열 순서: 회사명 | 시장구분 | 종목코드 | 업종
        for r in rows:
            tds = [re.sub(r"<[^>]+>", "", t).strip()
                   for t in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            if len(tds) < 3:
                continue
            name, market, code = tds[0], tds[1], tds[2].strip()
            if re.fullmatch(r"[0-9A-Z]{6}", code):
                out.append((code, name, "코스닥" if "코스닥" in market else "유가"))
        print(f"  개별주식 유니버스: {len(out)}종목")
        return out
    except Exception as e:
        print(f"  KIND 실패: {type(e).__name__} {e}")
        return []


def load_universe():
    uni = load_etfs() + load_stocks()
    # 코드 중복 제거 (ETF 우선)
    seen, out = set(), []
    for c, n, k in uni:
        if c in seen:
            continue
        seen.add(c)
        out.append([c, n, k])
    if out:
        C.write_json(UNIVERSE_CACHE, out)
        return out
    if os.path.exists(UNIVERSE_CACHE):
        print("  → 캐시 유니버스 사용")
        return json.load(open(UNIVERSE_CACHE, encoding="utf-8"))
    raise SystemExit("국내 유니버스를 구할 수 없다.")


def parse_sise(raw: bytes):
    """
    네이버 siseJson은 정식 JSON이 아니다. 홑따옴표에 후행 콤마가 붙는다.
    문자열 안에 콤마가 없는 숫자 표라 아래 치환으로 충분하다.
    """
    t = raw.decode("utf-8", "replace").strip().replace("'", '"')
    t = re.sub(r",\s*]", "]", t)
    t = re.sub(r",\s*}", "}", t)
    rows = json.loads(t)
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    bars = []
    for r in rows[1:]:
        try:
            d, o, h, l, c, v = r[0], r[1], r[2], r[3], r[4], r[5]
            c = float(c)
            if c <= 0:
                continue
            ds = str(d)
            bars.append({
                "date": f"{ds[0:4]}-{ds[4:6]}-{ds[6:8]}" if len(ds) == 8 else ds,
                "o": float(o or c), "h": float(h or c), "l": float(l or c),
                "c": c, "v": float(v or 0),
            })
        except (IndexError, TypeError, ValueError):
            continue
    return bars


def main():
    C.ensure_data_dirs("kr")
    throttle = C.Throttle()

    uni = load_universe()
    limit = int(os.environ.get("LIMIT") or 0)
    if limit:
        uni = uni[:limit]
    workers = int(os.environ.get("WORKERS") or 8)

    today = datetime.date.today()
    start = (today - datetime.timedelta(days=400)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    print(f"국내 보조지표 산출 시작 — {len(uni)}종목, 동시 {workers}")

    def one(item):
        code, name, kind = item
        try:
            raw = C.http_get(SISE.format(code=code, s=start, e=end),
                             C.NAVER_HEADERS, timeout=25, tries=4,
                             throttle=throttle)
        except Exception:
            return None
        bars = parse_sise(raw)
        if len(bars) < 30:
            return None
        res = I.compute_all(bars)
        if not res.get("ok"):
            return None
        row = I.to_row(code, name, res)
        row["kind"] = kind
        return row

    rows = [r for r in C.run_pool(uni, one, workers, "KR", 300) if r]
    rows.sort(key=lambda r: r["ticker"])

    print(f"  429/오류 브레이크 {throttle.hits}회")
    C.guard_ratio(len(rows), len(uni), 0.5, "국내")

    cols = I.CSV_COLUMNS + ["kind"]
    C.write_csv(os.path.join(C.DATA, "indicators_kr.csv"), cols, rows)
    counts = C.write_shards("kr", rows)
    print(f"  샤드 {len(counts)}개")

    C.write_json(os.path.join(C.DATA, "index_kr.json"),
                 [[r["ticker"], r["name"], r.get("kind", "")] for r in rows])

    C.write_json(os.path.join(C.DATA, "meta_kr.json"), {
        "updated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "count": len(rows),
        "universe": len(uni),
        "asOf": rows[-1]["date"] if rows else None,
    }, compact=False)


if __name__ == "__main__":
    main()
