import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash


load_dotenv()


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))


# -------------------------------------------------------------------
# Password hashing
# -------------------------------------------------------------------

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


# -------------------------------------------------------------------
# Temporary in-memory user store
# -------------------------------------------------------------------
#
# Production-shaped for learning.
# NOT production storage:
# - lost on restart
# - not shared between workers
# - no durable persistence
#
# Structure:
#
# users = {
#     "alice": {
#         "username": "alice",
#         "password_hash": "..."
#     }
# }
#

users: dict[str, dict[str, str]] = {}


def create_user(username: str, password: str) -> dict[str, str]:
    if username in users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    user = {
        "username": username,
        "password_hash": hash_password(password),
    }

    users[username] = user

    return user


def authenticate_user(
    username: str,
    password: str,
) -> dict[str, str] | None:

    user = users.get(username)

    if user is None:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return user


# -------------------------------------------------------------------
# JWT creation
# -------------------------------------------------------------------

def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


# -------------------------------------------------------------------
# Bearer authentication
# -------------------------------------------------------------------

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, str]:

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={
                "require": ["sub", "iat", "exp"],
            },
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload["sub"]

    user = users.get(username)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user