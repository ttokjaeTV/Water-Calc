"""배포 직전 _site/data 의 JSON 을 우수회원 입장 코드로 암호화한다.

- 키: PBKDF2-SHA256(정규화한 코드, "ttokjae-member-key-v1", 200000회) → AES-256-GCM
- 형식: {"__enc":1,"z":1,"iv":base64,"ct":base64}  (z=1: 암호화 전에 zlib 압축)
- 브라우저 쪽 복호화는 https://ttokjaetv.github.io/member-gate.js 의 MemberGate.decrypt
- 코드는 레포 Secrets 의 MEMBER_CODE 에서 받는다. 없으면 실패한다 —
  암호화 안 된 데이터가 새 화면과 함께 배포되는 일을 막기 위해서다.
- 캐시(data/)는 평문 그대로 두고 배포본(_site/data)만 암호화한다.
"""
import base64
import hashlib
import json
import os
import re
import sys
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_SALT = b"ttokjae-member-key-v1"
VERIFY_SALT = b"ttokjae-member-verify-v1"
ITER = 200000


def norm(s: str) -> str:
    return re.sub(r"[\s\-_.]+", "", s.strip().lower())


def main() -> int:
    raw = os.environ.get("MEMBER_CODE", "")
    code = norm(raw)
    if not code:
        print("::error::MEMBER_CODE 시크릿이 없습니다. Settings → Secrets and variables → Actions 에 등록하세요.")
        return 1
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/data")
    key = hashlib.pbkdf2_hmac("sha256", code.encode(), KEY_SALT, ITER)
    aes = AESGCM(key)
    verifier = base64.b64encode(hashlib.pbkdf2_hmac("sha256", code.encode(), VERIFY_SALT, ITER)).decode()
    print(f"검증값(member-gate.js 의 verifier 와 같아야 함): {verifier}")

    n = before = after = 0
    for p in sorted(root.rglob("*.json")):
        data = p.read_bytes()
        if data[:12].find(b'"__enc"') != -1:
            continue
        iv = os.urandom(12)
        ct = aes.encrypt(iv, zlib.compress(data, 9), None)
        out = json.dumps({"__enc": 1, "z": 1,
                          "iv": base64.b64encode(iv).decode(),
                          "ct": base64.b64encode(ct).decode()}, separators=(",", ":"))
        p.write_text(out, encoding="utf-8")
        n += 1
        before += len(data)
        after += len(out)
    if n == 0:
        print("::error::암호화할 JSON 이 없습니다.")
        return 1
    print(f"암호화 {n}개 파일: {before/1e6:.1f}MB → {after/1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
