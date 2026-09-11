import os
import time
import jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
import models

# ── Short-lived session cache (Removed) ───────────────────────────────────────
# The in-memory session cache has been removed to support production multi-worker
# scaling. Session validation is now strictly database-backed.

def invalidate_session_cache(session_id: str):
    """No-op. Left for backward compatibility with routers calling this on logout."""
    pass

import logging
logger = logging.getLogger(__name__)

# JWT_SECRET_KEY MUST be provided — application refuses to start without it.
# Generate a secure key with: python -c "import secrets; print(secrets.token_hex(64))"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "FATAL: JWT_SECRET_KEY environment variable is not set. "
        "The application cannot start without a secret key. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(64))\" "
        "and add it to your .env file or deployment environment variables."
    )

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Password hashing setup
import bcrypt


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    # Strip all non-numeric characters
    digits = "".join(filter(str.isdigit, phone))
    # Standardise to last 10 digits
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def hash_password(password: str) -> str:
    passwd = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(passwd, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        passwd = plain_password.encode('utf-8')
        hashed = hashed_password.encode('utf-8')
        return bcrypt.checkpw(passwd, hashed)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access", "iss": "retailfix_crm", "aud": "retailfix_users"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "iss": "retailfix_crm", "aud": "retailfix_users"})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


import re

def validate_password_strength(password: str):
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise ValueError("Password must contain at least one special character.")


class CurrentUser:
    def __init__(self, auth_user, business_user, role: str, session_id: str, username: str):
        self.auth_user = auth_user      # models.User
        self.user = business_user        # models.Admin / models.Salesman / models.Telecaller
        self.id = auth_user.id
        self.role = role
        self.session_id = session_id
        self.username = username


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> CurrentUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        token = cookie_token
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            csrf_token = request.headers.get("X-CSRF-Token")
            cookie_csrf = request.cookies.get("csrf_token")
            if not csrf_token or not cookie_csrf or csrf_token != cookie_csrf:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or incorrect")
    
    if not token:
        print("DEBUG: NO TOKEN FOUND")
        raise credentials_exception

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], audience="retailfix_users", issuer="retailfix_crm")
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        session_id: str = payload.get("jti") or payload.get("session_id")
        username: str = payload.get("username")

        if user_id is None or role is None or session_id is None:
            print("DEBUG: PAYLOAD MISSING DATA", payload)
            raise credentials_exception
    except jwt.ExpiredSignatureError:
        print("DEBUG: JWT EXPIRED")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError as e:
        print("DEBUG: JWT ERROR", str(e))
        raise credentials_exception

    # ── Database Validation Path ─────────────────────────────────────────
    # Check if unified user is active in DB
    auth_user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.is_active == True
    ).first()
    if not auth_user:
        raise credentials_exception

    # Check if user is locked
    now_ms = int(time.time() * 1000)
    if auth_user.locked_until and auth_user.locked_until > now_ms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is locked. Contact your administrator or try again later."
        )

    # Force password change check
    if auth_user.must_change_password:
        allowed_paths = ["/auth/change-password", "/auth/logout", "/auth/me", "/auth/refresh"]
        if request.url.path not in allowed_paths and request.method != "OPTIONS":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password change required"
            )

    # Check if session is active and not revoked in DB
    session = db.query(models.UserSession).filter(
        models.UserSession.id == session_id,
        models.UserSession.is_revoked == False
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check session expiry date
    if session.expires_at < now_ms:
        session.is_revoked = True
        db.commit()
        invalidate_session_cache(session_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check idle timeout
    IDLE_TIMEOUT_MS = 15 * 60 * 1000
    if session.last_activity and (now_ms - session.last_activity > IDLE_TIMEOUT_MS):
        session.is_revoked = True
        db.commit()
        invalidate_session_cache(session_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired due to inactivity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update session's last activity (throttled to once every 60s)
    if not session.last_activity or now_ms - session.last_activity > 60000:
        session.last_activity = now_ms
        db.commit()

    # Resolve business role-specific record for backward compatibility
    business_user = None
    role_lower = role.lower()
    if role_lower == "admin":
        business_user = db.query(models.Admin).filter(models.Admin.id == user_id).first()
    elif role_lower == "salesman":
        business_user = db.query(models.Salesman).filter(models.Salesman.id == user_id, models.Salesman.active == True).first()
    elif role_lower == "telecaller":
        business_user = db.query(models.Telecaller).filter(models.Telecaller.id == user_id, models.Telecaller.active == True).first()
    elif role_lower in ["factory", "inventory", "manager"]:
        business_user = auth_user

    if business_user is None:
        business_user = auth_user

    current_user = CurrentUser(
        auth_user=auth_user,
        business_user=business_user,
        role=role_lower,
        session_id=session_id,
        username=username
    )

    return current_user


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = [r.lower() for r in allowed_roles]

    def __call__(self, current_user: CurrentUser = Depends(get_current_user)):
        if current_user.role.lower() not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource"
            )
        return current_user
