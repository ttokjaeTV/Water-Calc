# -*- coding: utf-8 -*-
"""수집 스크립트 공용 유틸 — HTTP 재시도, 동시 실행, 산출물 쓰기."""

import json
import os
import time
import random
import gzip
import io
import csv
import urllib.request
import urllib.error
import concurrent.futures as cf
from typing import Callable, Iterable, List, Dict, Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

YAHOO_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}

NAVER_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Referer": "https://finance.naver.com/",
}


class Throttle:
    """
    429를 맞으면 전체 워커가 함께 느려지도록 하는 공용 브레이크.
    종목별로 개별 재시도만 하면 계속 벽에 부딪히기 때문에,
    한 번 막히면 잠시 모두가 쉬어간다.
    """

    def __init__(self):
        self.until = 0.0
        self.hits = 0

    def wait(self):
        d = self.until - time.time()
        if d > 0:
            time.sleep(d)

    def penalize(self, seconds: float):
        self.hits += 1
        self.until = max(self.until, time.time() + seconds)


def http_get(url: str, headers: Dict[str, str], timeout: int = 30,
             tries: int = 5, throttle: Throttle = None) -> bytes:
    """gzip 해제 + 429/5xx 지수 백오프."""
    h = dict(headers)
    h.setdefault("Accept-Encoding", "gzip")
    last = None
    for a in range(tries):
        if throttle:
            throttle.wait()
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 502, 503, 504):
                back = min(60, (2 ** a) + random.uniform(0, 1.5))
                if throttle and e.code == 429:
                    throttle.penalize(back)
                time.sleep(back if not throttle else 0)
                continue
            raise
        except Exception as e:            # 타임아웃·연결 끊김
            last = e
            time.sleep(min(20, 2 ** a))
            continue
    raise last if last else RuntimeError("http_get 실패: " + url)


def get_json(url: str, headers: Dict[str, str], **kw) -> Any:
    return json.loads(http_get(url, headers, **kw))


def run_pool(items: Iterable, fn: Callable, workers: int = 10,
             label: str = "", every: int = 500) -> List:
    """동시 실행 + 진행 로그. 예외는 삼키고 None으로 남긴다."""
    items = list(items)
    out, done = [], 0
    t0 = time.time()

    def safe(x):
        try:
            return fn(x)
        except Exception:
            return None

    with cf.ThreadPoolExecutor(workers) as ex:
        for r in ex.map(safe, items):
            out.append(r)
            done += 1
            if every and done % every == 0:
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (len(items) - done) / rate / 60 if rate else 0
                ok = sum(1 for x in out if x)
                print(f"  [{label}] {done}/{len(items)}  성공 {ok}  "
                      f"{rate:.1f}건/초  남은 예상 {eta:.1f}분", flush=True)
    print(f"  [{label}] 완료 {done}건 / {time.time()-t0:.0f}초", flush=True)
    return out


def ensure_data_dirs(*subs: str):
    os.makedirs(DATA, exist_ok=True)
    for s in subs:
        os.makedirs(os.path.join(DATA, s), exist_ok=True)


def write_csv(path: str, columns: List[str], rows: List[Dict]):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path)
    print(f"  → {os.path.relpath(path, ROOT)}  {len(rows)}행 "
          f"{os.path.getsize(path)/1024:.0f}KB")


def write_json(path: str, obj: Any, compact: bool = True):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    print(f"  → {os.path.relpath(path, ROOT)}  "
          f"{os.path.getsize(path)/1024:.0f}KB")


def shard_key(ticker: str) -> str:
    """
    프론트가 필요한 조각만 받도록 티커 첫 글자로 나눈다.
    전체를 한 파일로 두면 첫 로딩에 2MB를 받게 되기 때문이다.
    """
    c = (ticker or "_")[0].upper()
    return c if c.isalnum() else "_"


def write_shards(subdir: str, rows: List[Dict], key: str = "ticker"):
    """{티커: {지표...}} 형태로 조각내어 저장."""
    ensure_data_dirs(subdir)
    buckets: Dict[str, Dict] = {}
    for r in rows:
        buckets.setdefault(shard_key(r[key]), {})[r[key]] = r
    for k, v in sorted(buckets.items()):
        write_json(os.path.join(DATA, subdir, f"{k}.json"), v)
    return {k: len(v) for k, v in buckets.items()}


def guard_ratio(ok: int, total: int, floor: float = 0.5, what: str = ""):
    """
    확보율이 바닥 밑이면 실패로 끝낸다.
    깨진 데이터가 배포되면 구독자 화면이 통째로 비어버리는 게 더 나쁘다.
    """
    ratio = ok / total if total else 0
    print(f"  확보율 {what}: {ok}/{total} = {ratio*100:.1f}%")
    if ratio < floor:
        raise SystemExit(
            f"확보율 {ratio*100:.1f}% < {floor*100:.0f}% — 배포 중단. "
            f"소스 응답 구조 변경이나 차단을 의심할 것.")
