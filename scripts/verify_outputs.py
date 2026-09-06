# -*- coding: utf-8 -*-
"""
배포 직전 산출물 점검.

깨진 데이터가 배포되면 구독자 화면이 통째로 비어버린다.
그것보다는 배포를 멈추는 편이 낫다.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def main() -> int:
    missing = [f for f in ("macro.json", "bubble.json")
               if not os.path.exists(os.path.join(DATA, f))]
    if missing:
        print(f"필수 산출물 없음: {missing}")
        return 1

    for d in ("us", "kr"):
        p = os.path.join(DATA, d)
        n = len([x for x in os.listdir(p) if x.endswith(".json")]) if os.path.isdir(p) else 0
        print(f"  {d} 샤드 {n}개")

    macro = json.load(open(os.path.join(DATA, "macro.json"), encoding="utf-8"))
    got = [k for k, v in macro.items()
           if k not in ("updated", "errors", "yieldCurveSource") and v]
    print(f"  매크로 확보 {len(got)}개")

    errs = macro.get("errors") or []
    if errs:
        print("  매크로 수집 실패 항목:")
        for e in errs:
            print(f"   - {e.get('source')}: {str(e.get('error'))[:90]}")

    src = macro.get("yieldCurveSource")
    if src and "근사" in src:
        print(f"  ! 장단기 금리차가 근사치다 — {src}")

    # 신규상장 목록은 전종목 수집이 돌아야 생긴다. 없으면 deploy 모드로만
    # 며칠 돈 상태라는 뜻이라, 화면에서 '신규상장' 표기가 안 나온다.
    for mk in ("us", "kr"):
        p = os.path.join(DATA, f"pending_{mk}.json")
        if os.path.exists(p):
            n = len(json.load(open(p, encoding="utf-8")))
            print(f"  pending_{mk}: {n}종목 (신규상장 등)")
        else:
            print(f"  ! pending_{mk}.json 없음 — 전종목 수집이 한 번 돌아야 생긴다")

    total = 0
    for base, _, files in os.walk(DATA):
        for f in files:
            total += os.path.getsize(os.path.join(base, f))
    print(f"  data/ 총 {total/1024/1024:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
