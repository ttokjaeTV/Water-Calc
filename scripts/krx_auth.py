# -*- coding: utf-8 -*-
"""
KRX 정보데이터시스템 로그인 준비.

data.krx.co.kr 은 2026년부터 전면 로그인제다. 비로그인이면 400이나 빈 응답이
돌아오는데, 에러 메시지가 원인을 알려주지 않아 엉뚱한 데를 파기 쉽다.

절대 규칙 (krx-login 스킬)
  - 자격증명 값을 읽어서 출력하지 않는다. 로그에 남기지 않는다.
  - 성공/실패와 경로만 남긴다.
  - krx.env 는 git 에 올리지 않는다.

찾는 순서
  1) 이미 설정된 KRX_ID / KRX_PW 환경변수 (GitHub Actions 는 여기로 들어온다)
  2) KRX_ENV_FILE 이 가리키는 파일
  3) 알려진 경로들의 krx.env
"""

import os
import sys

CANDIDATES = [
    "/sessions/great-tender-lovelace/mnt/.secrets/krx.env",
    os.path.expanduser("~/.secrets/krx.env"),
    r"C:\Users\이상준\Desktop\Claude\.secrets\krx.env",
]


def _load_env_file(path: str) -> bool:
    """
    krx.env 를 환경변수로 올린다.
    utf-8-sig 로 여는 게 중요하다 — 이 파일에는 BOM 이 붙어 있어서
    그냥 utf-8 로 읽으면 첫 키가 'KRX_ID' 가 아니라 '\ufeffKRX_ID' 가 된다.
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip().lstrip("\ufeff")
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().lstrip("\ufeff")
                if k and not os.environ.get(k):
                    os.environ[k] = v.strip()
        return True
    except Exception:
        return False


def ensure(verbose: bool = True) -> bool:
    """KRX_ID / KRX_PW 를 환경변수에 준비한다. 값은 절대 출력하지 않는다."""
    if os.environ.get("KRX_ID") and os.environ.get("KRX_PW"):
        if verbose:
            print("  KRX 자격증명: 환경변수에서 확인")
        return True

    paths = []
    if os.environ.get("KRX_ENV_FILE"):
        paths.append(os.environ["KRX_ENV_FILE"])
    paths += CANDIDATES

    for p in paths:
        if os.path.exists(p) and _load_env_file(p):
            if os.environ.get("KRX_ID") and os.environ.get("KRX_PW"):
                if verbose:
                    print(f"  KRX 자격증명: {p} 에서 로드")
                return True

    if verbose:
        print("  KRX 자격증명 없음 — KRX 의존 항목은 건너뛴다")
    return False


def login(verbose: bool = True) -> bool:
    """실제 로그인까지 수행. pykrx 가 없으면 False."""
    if not ensure(verbose):
        return False
    try:
        from pykrx.website.comm import auth
    except ImportError:
        if verbose:
            print("  pykrx 미설치 — pip install pykrx 필요")
        return False
    try:
        auth.login_krx(os.environ["KRX_ID"], os.environ["KRX_PW"])
        return True
    except Exception as e:
        # 예외 문구에 자격증명이 섞일 수 있으니 타입만 남긴다.
        if verbose:
            print(f"  KRX 로그인 실패: {type(e).__name__}")
        return False


if __name__ == "__main__":
    sys.exit(0 if ensure() else 1)
