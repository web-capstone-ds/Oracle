import os
import bcrypt
from datetime import datetime, timedelta, timezone
from jose import jwt

JWT_SECRET = os.getenv("AUTH_JWT_SECRET", "CHANGE_ME_32_CHARS_MIN")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("AUTH_JWT_EXPIRE_HOURS", "8"))

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

def create_access_token(operator_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": operator_id,
        "role": role,
        "exp": expires,
        "iat": now
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
