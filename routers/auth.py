import uuid
import time
import jwt
import secrets
import random
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
import models
from email_service import send_otp_email
from auth_utils import (
    hash_password,

    verify_password,
    create_access_token,
    create_refresh_token,
    get_current_user, RoleChecker,
    CurrentUser,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    validate_password_strength,
    invalidate_session_cache
)

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_MAX_PER_MINUTE = 10
REFRESH_MAX_PER_MINUTE = 20
OTP_MAX_PER_MINUTE = 3

def _db_rate_limit(request: Request, db: Session, endpoint: str, max_requests: int):
    ip = request.client.host if request.client else "unknown"
    now_ms = int(time.time() * 1000)
    cutoff = now_ms - 60000
    
    # Delete old records occasionally to prevent table bloat (optional, but good for SQLite/Postgres)
    import random
    if random.random() < 0.05:
        db.query(models.RateLimit).filter(models.RateLimit.timestamp < cutoff).delete()
        db.commit()

    count = db.query(models.RateLimit).filter(
        models.RateLimit.ip_address == ip,
        models.RateLimit.endpoint == endpoint,
        models.RateLimit.timestamp > cutoff
    ).count()

    if count >= max_requests:
        raise HTTPException(status_code=429, detail="Too Many Requests. Please try again later.")

    new_limit = models.RateLimit(
        id=str(uuid.uuid4()),
        ip_address=ip,
        endpoint=endpoint,
        timestamp=now_ms
    )
    db.add(new_limit)
    db.commit()


def rate_limit_login(request: Request, db: Session = Depends(get_db)):
    """Rate limiter for /login — 10 attempts per minute per IP."""
    _db_rate_limit(request, db, "login", LOGIN_MAX_PER_MINUTE)


def rate_limit_refresh(request: Request, db: Session = Depends(get_db)):
    """Rate limiter for /refresh — 20 attempts per minute per IP."""
    _db_rate_limit(request, db, "refresh", REFRESH_MAX_PER_MINUTE)


def rate_limit_otp(request: Request, db: Session = Depends(get_db)):
    """Rate limiter for /forgot-password and /reset-password — 3 per minute per IP."""
    _db_rate_limit(request, db, "otp", OTP_MAX_PER_MINUTE)


# Backward-compatible alias
rate_limit_ip = rate_limit_login


class LoginPayload(BaseModel):
    username: str  # maps to username, name, or phone
    password: str  # password or pin
    role: str      # admin, salesman, telecaller


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    csrf_token: Optional[str] = None
    role: str
    username: str
    user_id: str
    must_change_password: bool
    phone: Optional[str] = ""
    email: Optional[str] = ""
    created_at: Optional[int] = 0


class RefreshPayload(BaseModel):
    refresh_token: str


class PasswordChangePayload(BaseModel):
    old_password: str
    new_password: str


class SessionOut(BaseModel):
    id: str
    ip_address: str
    user_agent: str
    last_login: int
    last_activity: int
    expires_at: int
    is_current: bool


@router.post(
    "/login",
    response_model=LoginResponse,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string", "description": "Username, name, or phone number"},
                            "password": {"type": "string", "description": "Password or PIN"},
                            "role": {"type": "string", "description": "Role (admin, salesman, telecaller). Optional for auto-detection."}
                        },
                        "required": ["username", "password"]
                    }
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string", "description": "Username, name, or phone number"},
                            "password": {"type": "string", "description": "Password or PIN"}
                        },
                        "required": ["username", "password"]
                    }
                }
            }
        }
    }
)
async def login(request: Request, response: Response, db: Session = Depends(get_db), _: None = Depends(rate_limit_ip)):
    content_type = request.headers.get("content-type", "")
    username = None
    password = None
    role = None

    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        username = (form.get("username") or "").strip()
        password = (form.get("password") or "").strip()
    else:
        try:
            body = await request.json()
            username = (body.get("username") or "").strip()
            password = (body.get("password") or "").strip()
            role = body.get("role")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid request payload")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    client_ip = request.client.host if request.client else ""
    now_ms = int(time.time() * 1000)

    # Clean username if it looks like a phone number
    from auth_utils import normalize_phone
    import re
    if re.match(r"^[0-9\+\-\s\(\)]+$", username):
        username = normalize_phone(username)

    # Apply auto-role detection rules — try multiple identifiers
    if "@" in username:
        # Email login — try admin first, then salesman/telecaller
        user = db.query(models.User).filter(
            models.User.email == username,
        ).first()
    else:
        # Try Employee ID for salesman
        user = db.query(models.User).filter(
            models.User.employee_id == username,
            models.User.role == "salesman"
        ).first()
        
        if not user:
            # Try Employee ID for telecaller
            user = db.query(models.User).filter(
                models.User.employee_id == username,
                models.User.role == "telecaller"
            ).first()

        if not user:
            # Try Employee ID for factory worker
            user = db.query(models.User).filter(
                models.User.employee_id == username,
                models.User.role == "factory"
            ).first()

        if not user:
            # Try username for any role (admin can login with 'admin' username)
            user = db.query(models.User).filter(
                models.User.username == username
            ).first()

        if not user:
            # Try mobile number for salesman/telecaller
            user = db.query(models.User).filter(
                models.User.mobile == username,
                models.User.role.in_(["salesman", "telecaller"])
            ).first()

    if user:
        # Check lockout
        if user.locked_until and user.locked_until > now_ms:
            time_left = int((user.locked_until - now_ms) / 1000)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account is locked. Please try again after {time_left} seconds or contact your administrator."
            )

    import asyncio
    success = False
    if user:
        success = await asyncio.to_thread(verify_password, password, user.password_hash)

    # Intentionally removed credential logging. Only log safe authentication results.

    # Log login attempt
    attempt = models.LoginAttempt(
        id=str(uuid.uuid4()),
        username=username,
        role=user.role if user else role or "unknown",
        ip_address=client_ip,
        timestamp=now_ms,
        success=success
    )
    db.add(attempt)

    if not success:
        if user:
            # Increment failed attempts
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now_ms + 15 * 60 * 1000 # 15 minutes lockout
                logger.warning(f"User {user.username} locked out due to 5 consecutive login failures.")
                # Log account lock audit
                lock_audit = models.AuditLog(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    username=user.username,
                    role=user.role,
                    action="Account Locked",
                    ip_address=client_ip,
                    timestamp=now_ms,
                    details="Account locked automatically due to 5 failed login attempts in 15 minutes"
                )
                db.add(lock_audit)
            db.commit()

        # Audit log failed login
        fail_audit = models.AuditLog(
            id=str(uuid.uuid4()),
            user_id=user.id if user else "unknown",
            username=username,
            role=user.role if user else role or "unknown",
            action="Failed Login",
            ip_address=client_ip,
            timestamp=now_ms,
            details=f"Failed login attempt for username: {username}"
        )
        db.add(fail_audit)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Reset lockouts on successful login
    user.failed_login_attempts = 0
    user.locked_until = 0
    user.last_login = now_ms

    # Success: Create UserSession
    session_id = str(uuid.uuid4())
    refresh_expire_ms = now_ms + REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60 * 1000

    new_session = models.UserSession(
        id=session_id,
        user_id=user.id,
        role=user.role,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", ""),
        last_login=now_ms,
        last_activity=now_ms,
        expires_at=refresh_expire_ms,
        is_revoked=False
    )
    db.add(new_session)

    # Success: Create AuditLog
    username_val = user.username
    success_audit = models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.id,
        username=username_val,
        role=user.role,
        action="Login",
        ip_address=client_ip,
        timestamp=now_ms,
        details="Successful authentication"
    )
    db.add(success_audit)
    if user.role.lower() == "telecaller":
        from models import log_telecaller_activity
        log_telecaller_activity(db, lead_id="", telecaller_name=username_val, action_type="Login", remark="Telecaller logged in.", request=request)
    db.commit()

    # Generate JWT Tokens
    token_claims = {
        "sub": user.id,
        "user_id": user.id,
        "role": user.role.lower(),
        "jti": session_id,
        "session_id": session_id,
        "username": username_val,
        "must_change_password": False
    }
    
    access_token = create_access_token(data=token_claims)
    refresh_token = create_refresh_token(data=token_claims)

    csrf_token = secrets.token_urlsafe(32)

    import os
    _env = os.environ.get("ENV", os.environ.get("ENVIRONMENT", "production"))
    _debug = os.environ.get("DEBUG", "False")
    is_secure = (_env == "production") and (_debug != "True")
    samesite_val = "none" if is_secure else "lax"
    
    response.set_cookie(key="access_token", value=access_token, httponly=True, secure=is_secure, samesite=samesite_val)
    response.set_cookie(key="refresh_token", value=refresh_token, httponly=True, secure=is_secure, samesite=samesite_val)
    response.set_cookie(key="csrf_token", value=csrf_token, httponly=False, secure=is_secure, samesite=samesite_val)

    phone_val = ""
    email_val = ""
    created_at_val = 0
    role_lower = user.role.lower()
    if role_lower == "telecaller":
        t_user = db.query(models.Telecaller).filter(models.Telecaller.id == user.id).first()
        if t_user:
            phone_val = t_user.phone or ""
            email_val = t_user.email or ""
            created_at_val = t_user.created_at or 0
    elif role_lower == "salesman":
        s_user = db.query(models.Salesman).filter(models.Salesman.id == user.id).first()
        if s_user:
            phone_val = s_user.phone or ""
            email_val = s_user.email or ""
            created_at_val = s_user.created_at or 0

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
        role=user.role.lower(),
        username=username_val,
        user_id=user.id,
        must_change_password=user.must_change_password,
        phone=phone_val,
        email=email_val,
        created_at=created_at_val
    )


@router.post("/logout")
def logout(response: Response, current_user: CurrentUser = Depends(get_current_user), request: Request = None, db: Session = Depends(get_db)):
    session = db.query(models.UserSession).filter(models.UserSession.id == current_user.session_id).first()
    if session:
        session.is_revoked = True
        db.commit()

    # Evict from in-process session cache immediately
    invalidate_session_cache(current_user.session_id)

    # Disconnect websocket for this session
    from websocket_manager import ws_manager
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.disconnect_session(current_user.session_id))
    except RuntimeError:
        asyncio.run(ws_manager.disconnect_session(current_user.session_id))

    # Audit log logout
    logout_audit = models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        action="Logout",
        ip_address=request.client.host if request and request.client else "",
        timestamp=int(time.time() * 1000),
        details="User logged out"
    )
    db.add(logout_audit)
    if current_user.role.lower() == "telecaller":
        from models import log_telecaller_activity
        log_telecaller_activity(db, lead_id="", telecaller_name=current_user.username, action_type="Logout", remark="Telecaller logged out.", request=request)
    db.commit()

    import os
    is_dev = os.getenv("DEBUG", "False") == "True" or os.getenv("ENV", "production") == "development"
    is_secure = not is_dev
    samesite_val = "none" if is_secure else "lax"
    
    response.delete_cookie(key="access_token", httponly=True, secure=is_secure, samesite=samesite_val)
    response.delete_cookie(key="refresh_token", httponly=True, secure=is_secure, samesite=samesite_val)
    response.delete_cookie(key="csrf_token", httponly=False, secure=is_secure, samesite=samesite_val)

    return {"status": "success", "message": "Successfully logged out"}


@router.post("/logout-all")
def logout_all_devices(current_user: CurrentUser = Depends(get_current_user), request: Request = None, db: Session = Depends(get_db)):
    # Revoke all active sessions for this user
    active_sessions = db.query(models.UserSession).filter(
        models.UserSession.user_id == current_user.id,
        models.UserSession.role == current_user.role,
        models.UserSession.is_revoked == False
    ).all()

    for s in active_sessions:
        s.is_revoked = True
        # Evict each session from the in-process cache
        invalidate_session_cache(s.id)

    # Audit log logout all
    logout_audit = models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        action="Logout All Devices",
        ip_address=request.client.host if request and request.client else "",
        timestamp=int(time.time() * 1000),
        details="Logged out from all devices"
    )
    db.add(logout_audit)
    db.commit()

    return {"status": "success", "message": "Successfully logged out from all devices"}


@router.post("/refresh")
def refresh_token(request: Request, response: Response, payload: Optional[RefreshPayload] = None, db: Session = Depends(get_db), _: None = Depends(rate_limit_refresh)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )

    token = request.cookies.get("refresh_token")
    if not token and payload:
        token = payload.refresh_token

    if not token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    try:
        token_payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            audience="retailfix_users",
            issuer="retailfix_crm"
        )
        user_id: str = token_payload.get("sub")
        role: str = token_payload.get("role")
        session_id: str = token_payload.get("jti")
        username: str = token_payload.get("username")
        token_type: str = token_payload.get("type")

        if user_id is None or role is None or session_id is None or token_type != "refresh":
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    # Check if session is revoked in DB
    session = db.query(models.UserSession).filter(
        models.UserSession.id == session_id,
        models.UserSession.is_revoked == False
    ).first()
    if not session:
        raise credentials_exception

    # Check session expiry date
    now_ms = int(time.time() * 1000)
    if session.expires_at < now_ms:
        session.is_revoked = True
        db.commit()
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == user_id, models.User.is_active == True).first()
    if not user:
        raise credentials_exception

    # Generate new access token
    new_token_claims = {
        "sub": user_id,
        "user_id": user_id,
        "role": role.lower(),
        "jti": session_id,
        "session_id": session_id,
        "username": username,
        "must_change_password": user.must_change_password
    }
    new_access_token = create_access_token(data=new_token_claims)
    
    import os
    is_dev = os.getenv("DEBUG", "False") == "True" or os.getenv("ENV", "production") == "development"
    is_secure = not is_dev
    samesite_val = "none" if is_secure else "lax"
    
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(key="access_token", value=new_access_token, httponly=True, secure=is_secure, samesite=samesite_val)
    response.set_cookie(key="refresh_token", value=token, httponly=True, secure=is_secure, samesite=samesite_val)
    response.set_cookie(key="csrf_token", value=csrf_token, httponly=False, secure=is_secure, samesite=samesite_val)

    return {
        "access_token": new_access_token,
        "refresh_token": token,
        "csrf_token": csrf_token,
        "role": role.lower(),
        "username": username,
        "user_id": user_id
    }


@router.get("/me")
def get_me(current_user: CurrentUser = Depends(get_current_user)):
    user_data = {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "must_change_password": False,
        "phone": "",
        "email": "",
        "created_at": 0
    }
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        t_user = current_user.user
        if t_user:
            user_data["phone"] = getattr(t_user, "phone", "") or ""
            user_data["email"] = getattr(t_user, "email", "") or ""
            user_data["created_at"] = getattr(t_user, "created_at", 0) or 0
    elif role_lower == "salesman":
        s_user = current_user.user
        if s_user:
            user_data["phone"] = getattr(s_user, "phone", "") or ""
            user_data["email"] = getattr(s_user, "email", "") or ""
            user_data["created_at"] = getattr(s_user, "created_at", 0) or 0
    return user_data


@router.get("/sessions", response_model=List[SessionOut])
def get_sessions(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.query(models.UserSession).filter(
        models.UserSession.user_id == current_user.id,
        models.UserSession.role == current_user.role,
        models.UserSession.is_revoked == False
    ).order_by(models.UserSession.last_login.desc()).all()

    return [
        SessionOut(
            id=s.id,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            last_login=s.last_login,
            last_activity=s.last_activity or s.last_login,
            expires_at=s.expires_at,
            is_current=(s.id == current_user.session_id)
        )
        for s in sessions
    ]


@router.post("/sessions/revoke/{session_id}")
def revoke_session(session_id: str, current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.query(models.UserSession).filter(models.UserSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id and current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    session.is_revoked = True
    db.commit()
    
    # Disconnect websocket for this session
    from websocket_manager import ws_manager
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop.create_task(ws_manager.disconnect_session(session_id))
    else:
        loop.run_until_complete(ws_manager.disconnect_session(session_id))
        
    return {"status": "success", "message": "Session successfully revoked"}


@router.post("/unlock/{user_id}")
def unlock_user(user_id: str, current_user: CurrentUser = Depends(RoleChecker(["admin"])), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.locked_until = 0
    user.failed_login_attempts = 0
    db.commit()
    
    # Audit log unlock
    unlock_audit = models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        action="Unlock User Account",
        ip_address="",
        timestamp=int(time.time() * 1000),
        details=f"Admin unlocked account for user {user.username}"
    )
    db.add(unlock_audit)
    db.commit()
    return {"status": "success", "message": "Account successfully unlocked"}


@router.post("/change-password")
def change_password(payload: PasswordChangePayload, current_user: CurrentUser = Depends(get_current_user), request: Request = None, db: Session = Depends(get_db)):
    # 1. Verify old password is correct FIRST — fail-fast before any other check
    if not verify_password(payload.old_password, current_user.auth_user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid old password")

    # 2. Prevent password reuse BEFORE strength validation so this check is always
    #    reachable even when the existing password does not meet current policy.
    if verify_password(payload.new_password, current_user.auth_user.password_hash):
        raise HTTPException(status_code=400, detail="New password cannot be the same as the old password")

    # 3. Enforce password policy strength on the new password
    try:
        validate_password_strength(payload.new_password)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    new_hash = hash_password(payload.new_password)
    
    # 3. Update unified user record
    current_user.auth_user.password_hash = new_hash
    current_user.auth_user.must_change_password = False
    current_user.auth_user.updated_at = int(time.time() * 1000)

    # 4. Synchronize hash with legacy tables to prevent compatibility breakage
    if current_user.role == "admin":
        legacy = db.query(models.Admin).filter(models.Admin.id == current_user.id).first()
        if legacy:
            legacy.password_hash = new_hash
    elif current_user.role == "salesman":
        legacy = db.query(models.Salesman).filter(models.Salesman.id == current_user.id).first()
        if legacy:
            legacy.pin = new_hash
    elif current_user.role == "telecaller":
        legacy = db.query(models.Telecaller).filter(models.Telecaller.id == current_user.id).first()
        if legacy:
            legacy.pin = new_hash

    # Revoke other sessions on password change for security
    other_sessions = db.query(models.UserSession).filter(
        models.UserSession.user_id == current_user.id,
        models.UserSession.id != current_user.session_id
    ).all()
    for s in other_sessions:
        s.is_revoked = True
        
    if current_user.role.lower() == "telecaller":
        from models import log_telecaller_activity
        log_telecaller_activity(db, lead_id="", telecaller_name=current_user.username, action_type="Password Changed", remark="Telecaller changed account password.", request=request)
        
    db.commit()
    
    # Disconnect websocket for other sessions
    from websocket_manager import ws_manager
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    for s in other_sessions:
        if loop.is_running():
            loop.create_task(ws_manager.disconnect_session(s.id))
        else:
            loop.run_until_complete(ws_manager.disconnect_session(s.id))

    # Audit log password change
    change_audit = models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        action="Password Change",
        ip_address=request.client.host if request and request.client else "",
        timestamp=int(time.time() * 1000),
        details="User successfully changed password"
    )
    db.add(change_audit)
    db.commit()

    return {"status": "success", "message": "Password changed successfully"}


class ForgotPasswordRequest(BaseModel):
    email: str


class VerifyOTPRequest(BaseModel):
    email: str
    otp: str


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    new_password: str
    confirm_password: str


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db), _: None = Depends(rate_limit_otp)):
    email_clean = payload.email.strip().lower()
    
    # Look up user by email
    user = db.query(models.User).filter(models.User.email == email_clean).first()
    if not user:
        # Use generic message to prevent email enumeration attacks
        return {
            "status": "success",
            "message": "If this email is registered, an OTP code will be sent."
        }
        
    if not user.email:
        raise HTTPException(status_code=400, detail="User does not have a registered email address.")

    now_ms = int(time.time() * 1000)
    
    # Rate limiting: prevent OTP spam — only allow one request per 60 seconds
    recent_otp = db.query(models.PasswordResetOTP).filter(
        models.PasswordResetOTP.email == email_clean,
        models.PasswordResetOTP.created_at > (now_ms - 60000),  # 60 seconds
        models.PasswordResetOTP.is_used == False
    ).first()
    if recent_otp:
        raise HTTPException(
            status_code=429,
            detail="Please wait 60 seconds before requesting another OTP."
        )
        
    # Generate 6-digit OTP using secure random
    otp_code = "".join(secrets.choice("0123456789") for _ in range(6))
    hashed_otp = hash_password(otp_code)
    
    expires_at = now_ms + 10 * 60 * 1000  # 10 minutes in ms
    
    # Delete any existing OTP records for this email
    db.query(models.PasswordResetOTP).filter(models.PasswordResetOTP.email == email_clean).delete()
    
    # Save the new OTP record
    otp_record = models.PasswordResetOTP(
        id=str(uuid.uuid4()),
        user_id=user.id,
        email=email_clean,
        otp=hashed_otp,
        expires_at=expires_at,
        attempts=0,
        is_used=False,
        created_at=now_ms
    )
    db.add(otp_record)
    db.commit()
    
    # Send email via Brevo
    success = send_otp_email(recipient_email=email_clean, recipient_name=user.username, otp=otp_code)
    logger.info(f"Password reset OTP triggered for: {email_clean} (logged for local fallback/testing). Email sent: {success}")
    if not success:
        logger.warning(f"Failed to send password reset email via Brevo for {email_clean}. OTP still valid for manual delivery.")
        
    return {
        "status": "success",
        "message": "If this email is registered, an OTP code will be sent."
    }


@router.post("/verify-otp")
def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    email_clean = payload.email.strip().lower()
    now_ms = int(time.time() * 1000)
    
    # Retrieve the active (unexpired) OTP record matching the email
    otp_record = db.query(models.PasswordResetOTP).filter(
        models.PasswordResetOTP.email == email_clean,
        models.PasswordResetOTP.expires_at > now_ms,
        models.PasswordResetOTP.is_used == False
    ).order_by(models.PasswordResetOTP.created_at.desc()).first()
    
    if not otp_record:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")
        
    # Increment attempts first
    otp_record.attempts += 1
    db.commit()
    
    # Check attempts limit
    if otp_record.attempts > 5:
        db.delete(otp_record)
        db.commit()
        raise HTTPException(status_code=400, detail="Maximum verification attempts exceeded. Please request a new OTP.")
        
    # Verify the code
    if not verify_password(payload.otp, otp_record.otp):
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")
        
    # Mark the OTP as verified/used
    otp_record.is_used = True
    db.commit()
    
    return {"status": "success", "message": "OTP verified successfully."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db), _: None = Depends(rate_limit_otp)):
    email_clean = payload.email.strip().lower()
    
    # Validate password match
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
        
    # 1. Enforce password policy strength
    try:
        validate_password_strength(payload.new_password)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
        
    now_ms = int(time.time() * 1000)
    
    # 2. Retrieve verified OTP record (must be unexpired and is_used == True)
    otp_record = db.query(models.PasswordResetOTP).filter(
        models.PasswordResetOTP.email == email_clean,
        models.PasswordResetOTP.is_used == True,
        models.PasswordResetOTP.expires_at > now_ms
    ).first()
    
    if not otp_record or not verify_password(payload.otp, otp_record.otp):
        raise HTTPException(status_code=400, detail="Invalid or expired OTP request.")
            
    # 3. Find User
    user = db.query(models.User).filter(models.User.email == email_clean).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    # 4. Hash new password using bcrypt
    new_hash = hash_password(payload.new_password)
    user.password_hash = new_hash
    user.must_change_password = False
    user.updated_at = now_ms
    
    # 5. Revoke existing user sessions (forces logout of other active sessions)
    active_sessions = db.query(models.UserSession).filter(
        models.UserSession.user_id == user.id,
        models.UserSession.is_revoked == False
    ).all()
    for s in active_sessions:
        s.is_revoked = True
        
    db.commit()
    
    # Disconnect websockets for all active sessions of this user
    from websocket_manager import ws_manager
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    for s in active_sessions:
        if loop.is_running():
            loop.create_task(ws_manager.disconnect_session(s.id))
        else:
            loop.run_until_complete(ws_manager.disconnect_session(s.id))
        
    # 6. Synchronize password/PIN with legacy tables
    if user.role == "admin":
        legacy = db.query(models.Admin).filter(models.Admin.id == user.id).first()
        if legacy:
            legacy.password_hash = new_hash
    elif user.role == "salesman":
        legacy = db.query(models.Salesman).filter(models.Salesman.id == user.id).first()
        if legacy:
            legacy.pin = new_hash
    elif user.role == "telecaller":
        legacy = db.query(models.Telecaller).filter(models.Telecaller.id == user.id).first()
        if legacy:
            legacy.pin = new_hash
            
    # 7. Delete the OTP record (Delete OTP after successful reset)
    db.delete(otp_record)
    
    # Audit log the reset action
    reset_audit = models.AuditLog(
        id=str(uuid.uuid4()),
        user_id=user.id,
        username=user.username,
        role=user.role,
        action="Password Reset via OTP",
        ip_address="",
        timestamp=now_ms,
        details="Password successfully reset using OTP verification."
    )
    db.add(reset_audit)
    if user.role.lower() == "telecaller":
        from models import log_telecaller_activity
        log_telecaller_activity(db, lead_id="", telecaller_name=user.username, action_type="Password Reset", remark="Telecaller reset account password via OTP.", request=None)
    db.commit()
    
    return {"status": "success", "message": "Password reset successfully."}

