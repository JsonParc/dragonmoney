from __future__ import annotations

import hmac
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE = "stockbot_session"
MAX_AGE = 7 * 24 * 3600
MAX_FAILS = 5
LOCK_SECONDS = 300


class Auth:
    def __init__(self, secret_key: str, password: str):
        self._ser = URLSafeTimedSerializer(secret_key, salt="stockbot-web")
        self._password = password
        self._fails = 0
        self._locked_until = 0.0

    def login(self, password: str) -> str:
        if time.time() < self._locked_until:
            raise HTTPException(429, "로그인 시도가 너무 많습니다. 5분 뒤에 다시 시도하세요.")
        if not hmac.compare_digest(password or "", self._password):
            self._fails += 1
            if self._fails >= MAX_FAILS:
                self._locked_until = time.time() + LOCK_SECONDS
                self._fails = 0
            raise HTTPException(401, "비밀번호가 틀렸습니다.")
        self._fails = 0
        return self._ser.dumps({"u": "admin"})

    def require(self, request: Request) -> None:
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "로그인이 필요합니다.")
        try:
            self._ser.loads(token, max_age=MAX_AGE)
        except (BadSignature, SignatureExpired):
            raise HTTPException(401, "로그인이 필요합니다.")
