import uuid
import time
import os
import json
import logging
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import engine, SessionLocal, get_db
import models
import schemas
from routers import products, quotations, customers, payments, settings, leads, salesmen, telecallers, sheets_sync, followups, auth, reports, factory, inventory, factory_users
from auth_utils import get_current_user, CurrentUser

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Sentry Error Tracking (optional) ─────────────────────────────────────────
# Set SENTRY_DSN in your environment to enable production error tracking.
# Leave it empty (or unset) to disable — this block is a no-op when absent.
# Obtain a DSN at https://sentry.io → Settings → Projects → DSN
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        import logging as _logging

        sentry_sdk.init(
            dsn=_sentry_dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                LoggingIntegration(level=_logging.INFO, event_level=_logging.ERROR),
            ],
            # Capture 10% of transactions for performance monitoring
            traces_sample_rate=0.10,
            # Do not send PII (user IP, email) unless explicitly required
            send_default_pii=False,
        )
        logger.info("Sentry error tracking initialised (environment=%s).", os.getenv("SENTRY_ENVIRONMENT", "production"))
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but the 'sentry-sdk' package is not installed. "
            "Install it with: pip install sentry-sdk[fastapi]"
        )


# Database schema tables are verified and automatically created at startup.

from contextlib import asynccontextmanager
from fastapi import WebSocket, WebSocketDisconnect

from websocket_manager import ws_manager

def parse_followup_datetime(date_str: str, time_str: str):
    import datetime
    try:
        if not time_str:
            time_str = "12:00 PM"
        dt_str = f"{date_str} {time_str}"
        return datetime.datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")
    except Exception:
        try:
            return datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            return None


async def check_followup_alerts_job(engine):
    import datetime
    import time
    import asyncio
    from database import SessionLocal
    import models
    from models import create_notification
    import logging

    logger = logging.getLogger("main.scheduler")

    # Track followups already notified today to prevent spam
    overdue_notified_today: set = set()
    reminder_notified: set = set()  # (followup_id, minute_bucket)

    while True:
        # Run every 60 seconds
        await asyncio.sleep(60)
        
        db = SessionLocal()
        try:
            now = datetime.datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # Reset daily dedup set at midnight
            if now.hour == 0 and now.minute < 2:
                overdue_notified_today.clear()
            
            # Fetch pending follow-ups
            pending = db.query(models.LeadFollowup).filter(
                models.LeadFollowup.status == "Pending"
            ).all()
            
            for f in pending:
                lead = db.query(models.Lead).filter(models.Lead.id == f.lead_id).first()
                if not lead:
                    continue
                
                f_dt = parse_followup_datetime(f.follow_up_date, f.follow_up_time)
                if not f_dt:
                    continue
                
                # 1. Overdue: follow-up date is in the past — notify ONCE per day per followup
                if f.follow_up_date < today_str:
                    dedup_key = f"{f.id}:{today_str}"
                    if dedup_key not in overdue_notified_today:
                        overdue_notified_today.add(dedup_key)
                        msg = f"Overdue: Follow-up for {lead.customer_name} was scheduled on {f.follow_up_date} {f.follow_up_time}."
                        if f.assigned_to:
                            create_notification(db, message=msg, type="Followup Overdue", user_id=f.assigned_to, lead_id=lead.id)
                        if lead.salesman_name and lead.salesman_name != f.assigned_to:
                            create_notification(db, message=msg, type="Followup Overdue", user_id=lead.salesman_name, lead_id=lead.id)
                    
                # 2. Imminent/Due Soon Reminder: follow-up date is today, within next 60 minutes
                elif f.follow_up_date == today_str:
                    diff_mins = (f_dt - now).total_seconds() / 60.0
                    if 0 <= diff_mins <= 60:
                        # Bucket to 15-minute windows to avoid re-notifying every minute
                        minute_bucket = int(now.minute / 15)
                        remind_key = f"{f.id}:{today_str}:{minute_bucket}"
                        if remind_key not in reminder_notified:
                            reminder_notified.add(remind_key)
                            msg = f"Reminder: Follow-up with {lead.customer_name} is due in {int(diff_mins)} minutes! ({f.follow_up_time})"
                            if f.assigned_to:
                                create_notification(db, message=msg, type="Reminder", user_id=f.assigned_to, lead_id=lead.id)
                            if lead.salesman_name and lead.salesman_name != f.assigned_to:
                                create_notification(db, message=msg, type="Reminder", user_id=lead.salesman_name, lead_id=lead.id)
            
            db.commit()
        except Exception as e:
            logger.error(f"Error in check_followup_alerts_job: {e}")
            db.rollback()
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ws_manager = ws_manager
    import asyncio
    
    # Store main loop reference in ws_manager
    try:
        ws_manager.main_loop = asyncio.get_running_loop()
    except RuntimeError:
        ws_manager.main_loop = asyncio.get_event_loop()

    # Automatically create missing database tables
    try:
        logger.info("Initializing database tables...")
        from database import Base, engine
        import models
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully.")
        
        # Seed settings database (Only if not in production)
        if os.getenv("ENV", "development") != "production":
            try:
                logger.info("Seeding settings database...")
                from database import SessionLocal
                from seeder import seed_database
                db = SessionLocal()
                seed_database(db)
                db.close()
                logger.info("Settings database seeded successfully.")
            except Exception as e:
                logger.error(f"Seeding database failed: {e}")
        else:
            logger.info("Skipping automatic database seeder in production environment.")
            
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise
    
    # Start auto Google Sheets sync loop
    from routers.sheets_sync import run_auto_sync_loop
    sync_task = asyncio.create_task(run_auto_sync_loop(app))
    
    # Start follow-up alerts check loop
    alerts_task = asyncio.create_task(check_followup_alerts_job(engine))
    
    yield
    sync_task.cancel()
    alerts_task.cancel()

app = FastAPI(title="RetailFix API", version="1.0.0", lifespan=lifespan)
app.state.ws_manager = ws_manager

from collections import defaultdict
WS_RATE_LIMITS = defaultdict(list)

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = None
):
    client_ip = websocket.client.host if websocket.client else "unknown"
    now_ts = time.time()
    WS_RATE_LIMITS[client_ip] = [ts for ts in WS_RATE_LIMITS[client_ip] if now_ts - ts < 60]
    if len(WS_RATE_LIMITS[client_ip]) > 20:
        await websocket.accept()
        await websocket.close(code=4000, reason="Rate limit exceeded")
        return
    WS_RATE_LIMITS[client_ip].append(now_ts)

    if not token:
        token = websocket.query_params.get("token", "")
    
    if not token:
        token = websocket.cookies.get("access_token", "")
        
    if not token:
        logger.warning("WebSocket connection rejected: Missing token")
        await websocket.accept()
        await websocket.close(code=4001)
        return
        
    import jwt
    from auth_utils import JWT_SECRET_KEY, JWT_ALGORITHM
    from fastapi import WebSocketDisconnect
    
    db = SessionLocal()
    try:
        payload = jwt.decode(
            token, 
            JWT_SECRET_KEY, 
            algorithms=[JWT_ALGORITHM],
            audience="retailfix_users", 
            issuer="retailfix_crm"
        )
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        session_id = payload.get("session_id") or payload.get("jti")
        username: str = payload.get("username")
        token_type: str = payload.get("type")
        
        if not user_id or not role or not session_id or token_type != "access":
            raise jwt.PyJWTError("Invalid token payload")
            
        # Check DB session
        session = db.query(models.UserSession).filter(
            models.UserSession.id == session_id,
            models.UserSession.is_revoked == False
        ).first()
        if not session:
            raise jwt.PyJWTError("Session revoked or not found")
            
        # Check expiry
        now_ms = int(time.time() * 1000)
        if session.expires_at < now_ms:
            raise jwt.PyJWTError("Session expired")
            
        await ws_manager.connect(websocket, user_id, role, username, session_id)
        
        while True:
            # Maintain active connection
            await websocket.receive_text()
            
    except jwt.ExpiredSignatureError as err:
        logger.warning(f"WebSocket connection rejected: Token expired: {err}")
        await websocket.accept()
        await websocket.close(code=4002)
    except jwt.PyJWTError as err:
        logger.warning(f"WebSocket connection rejected: Invalid token: {err}")
        await websocket.accept()
        await websocket.close(code=4001)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)
    finally:
        db.close()

# Security Headers Middleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
            response = JSONResponse(
                status_code=500,
                content={"detail": "An internal server error occurred."}
            )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        is_dev = os.getenv("DEBUG", "False") == "True" or os.getenv("ENV", "production") == "development"

        # Fix: img-src must allow http: for local dev so html2canvas can load
        # images from http://localhost:8001/uploads/* during PDF generation.
        img_src = "img-src 'self' data: http: https:;" if is_dev else "img-src 'self' data: https:;"

        if is_dev and request.url.path in ["/docs", "/openapi.json", "/redoc"]:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                f"{img_src} "
                "connect-src 'self' http: https:;"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; {img_src}"
            )
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

class PayloadLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int = 5 * 1024 * 1024): # 5MB limit
        super().__init__(app)
        self.max_upload_size = max_upload_size

    async def dispatch(self, request: Request, call_next):
        if request.method in ["POST", "PUT", "PATCH"]:
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_upload_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Payload Too Large. Maximum allowed size is 5MB."}
                )
        return await call_next(request)

# Setup dynamic CORS origins
allowed_origins_raw = os.getenv("ALLOWED_ORIGINS")
if not allowed_origins_raw or allowed_origins_raw.strip() == "*" or allowed_origins_raw.strip() == "":
    allowed_origins = ["http://localhost:5173", "http://localhost:3000"]
else:
    allowed_origins = [org.strip() for org in allowed_origins_raw.split(",") if org.strip()]





# IMPORTANT: Starlette processes add_middleware() in REVERSE registration order.
# CORSMiddleware is added last so it becomes OUTERMOST and wraps ALL responses.
app.add_middleware(PayloadLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




# Global Exception Middleware for Crash Handling
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."}
    )


from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    if errors:
        err = errors[0]
        field = err.get("loc", ["field"])[-1]
        msg = err.get("msg", "")
        field_name = str(field).replace("_", " ").strip()
        if field_name == "username":
            field_name = "email"
            
        if "missing" in err.get("type", "") or "required" in msg.lower():
            detail_msg = f"{field_name.capitalize()} is required."
        else:
            detail_msg = f"Invalid {field_name}: {msg}."
    else:
        detail_msg = "Validation failed."
        
    return JSONResponse(
        status_code=422,
        content={"detail": detail_msg}
    )



app.include_router(products.router)
app.include_router(quotations.router)
app.include_router(customers.router)
app.include_router(payments.router)
app.include_router(settings.router)
app.include_router(leads.router)
app.include_router(salesmen.router)
app.include_router(telecallers.router)
app.include_router(sheets_sync.router)
app.include_router(auth.router)
app.include_router(followups.router)
app.include_router(reports.router)
app.include_router(factory.router)
app.include_router(inventory.router)
app.include_router(factory_users.router)


from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.routing import Route

upload_dir = os.path.abspath("uploads")
if not os.path.exists(upload_dir):
    os.makedirs(upload_dir)

# Fix: Wrap StaticFiles with a custom middleware that adds CORS headers.
# html2canvas fetches images from http://localhost:8001/uploads/* cross-origin
# (frontend is on :5173). Without Access-Control-Allow-Origin, the browser
# blocks the fetch and images appear blank in the generated PDF.
from starlette.middleware.base import BaseHTTPMiddleware as _BHM

class _UploadsCORSMiddleware(_BHM):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/uploads/"):
            origin = request.headers.get("origin")
            # Only echo back the origin if it is in our allowlist, or if no origin, omit the header
            if origin in allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        return response

app.add_middleware(_UploadsCORSMiddleware)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")



@app.get("/")
def root():
    return {"message": "RetailFix API is running", "docs": "/docs"}

@app.get("/health")
def health_check():
    db_status = "ok"
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {
        "status": "ok",
        "database": db_status,
        "websocket_connections": len(ws_manager.active_connections),
        "version": "1.0.0"
    }


@app.get("/notifications", response_model=list[schemas.NotificationOut])
def get_notifications(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    from sqlalchemy import or_, and_
    role_lower = current_user.role.lower()
    notifications = db.query(models.Notification).filter(
        or_(
            models.Notification.user_id == current_user.id,
            models.Notification.user_id == current_user.username,
            models.Notification.role == role_lower,
            and_(models.Notification.user_id == None, models.Notification.role == None)
        )
    ).order_by(models.Notification.created_at.desc()).limit(50).all()
    return notifications


@app.post("/notifications/read")
def mark_notifications_read(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Mark ALL notifications as read for the current user."""
    from sqlalchemy import or_
    role_lower = current_user.role.lower()
    db.query(models.Notification).filter(
        or_(
            models.Notification.user_id == current_user.id,
            models.Notification.user_id == current_user.username,
            models.Notification.role == role_lower
        )
    ).update({models.Notification.read: True}, synchronize_session=False)
    db.commit()
    return {"status": "success"}


@app.patch("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Mark a single notification as read."""
    notif = db.query(models.Notification).filter(models.Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    # Verify ownership
    if notif.user_id not in [current_user.id, current_user.username] and notif.role != current_user.role.lower():
        if current_user.role.lower() != "admin":
            raise HTTPException(status_code=403, detail="Forbidden")
    notif.read = True
    db.commit()
    return {"status": "success", "id": notification_id}


@app.delete("/notifications/{notification_id}")
def delete_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Delete a specific notification."""
    notif = db.query(models.Notification).filter(models.Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notif.user_id not in [current_user.id, current_user.username] and notif.role != current_user.role.lower():
        if current_user.role.lower() != "admin":
            raise HTTPException(status_code=403, detail="Forbidden")
    db.delete(notif)
    db.commit()
    return {"status": "deleted", "id": notification_id}


@app.get("/notifications/count")
def get_notifications_count(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Return count of unread notifications for the current user."""
    from sqlalchemy import or_, func
    role_lower = current_user.role.lower()
    count = db.query(func.count(models.Notification.id)).filter(
        or_(
            models.Notification.user_id == current_user.id,
            models.Notification.user_id == current_user.username,
            models.Notification.role == role_lower
        ),
        models.Notification.read == False
    ).scalar()
    return {"unread_count": count or 0}


# ── Audit Logs API ─────────────────────────────────────────────────────────────
@app.get("/admin/audit-logs")
def get_audit_logs(
    page: int = 1,
    page_size: int = 50,
    action: str = None,
    user_id: str = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Retrieve audit logs. Admin only."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    query = db.query(models.AuditLog)
    if action:
        query = query.filter(models.AuditLog.action.ilike(f"%{action}%"))
    if user_id:
        query = query.filter(models.AuditLog.user_id == user_id)
    total = query.count()
    logs = query.order_by(models.AuditLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username,
                "role": log.role,
                "action": log.action,
                "ip_address": log.ip_address,
                "timestamp": log.timestamp,
                "details": log.details,
            }
            for log in logs
        ]
    }


@app.get("/admin/login-attempts")
def get_login_attempts(
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Retrieve login attempt history. Admin only."""
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    total = db.query(models.LoginAttempt).count()
    attempts = db.query(models.LoginAttempt).order_by(
        models.LoginAttempt.timestamp.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "attempts": [
            {
                "id": a.id,
                "username": a.username,
                "role": a.role,
                "ip_address": a.ip_address,
                "timestamp": a.timestamp,
                "success": a.success,
            }
            for a in attempts
        ]
    }



# ── Seed default products if the catalog is empty ────────────────────────────
SEED_PRODUCTS = [
    {"name": "Supermarket Display Rack", "category": "Supermarket", "unit": "per piece", "price": 4999,
     "desc": "Heavy-duty adjustable shelving for organized display.", "hsn_code": "9403"},
    {"name": "Pharmacy Display Rack", "category": "Pharmacy", "unit": "per piece", "price": 3999,
     "desc": "Neatly display medicines for easy customer access.", "hsn_code": "9403"},
    {"name": "Garment Display Rack", "category": "Garment", "unit": "per piece", "price": 3999,
     "desc": "Attractive fixtures for folded & hanging apparel.", "hsn_code": "9403"},
    {"name": "Corner Shelf (Supermarket)", "category": "Supermarket", "unit": "per piece", "price": 3499,
     "desc": "Utilize every inch with stylish corner shelves.", "hsn_code": "9403"},
    {"name": "End Cap Display Rack", "category": "Supermarket", "unit": "per piece", "price": 4499,
     "desc": "Attract attention with displays at aisle ends.", "hsn_code": "9403"},
    {"name": "Wall-mounted Medicine Rack", "category": "Pharmacy", "unit": "per piece", "price": 2999,
     "desc": "Utilize walls for organized medicine displays.", "hsn_code": "9403"},
]



SEED_CUSTOMERS = [
    {"name": "Sharma Kirana Store", "phone": "9876543210", "email": "sharma.kirana@gmail.com", "city": "Bhopal", "address": "12, Govindpura Industrial Area", "gstin": "23AAAAA1111A1Z1"},
    {"name": "Verma Medicos", "phone": "9123456789", "email": "verma.medicos@yahoo.com", "city": "Indore", "address": "Shop No. 4, MG Road", "gstin": "23BBBBB2222B2Z2"},
    {"name": "Metro Garments", "phone": "9988776655", "email": "metro.garments@outlook.com", "city": "Jabalpur", "address": "Civic Center, Main Market", "gstin": ""},
]






@app.get("/backup")
def get_backup(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user), request: Request = None):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    products = db.query(models.Product).all()
    customers = db.query(models.Customer).all()
    quotations = db.query(models.Quotation).all()
    payments = db.query(models.Payment).all()
    leads = db.query(models.Lead).all()
    lead_followups = db.query(models.LeadFollowup).all()

    result = {
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "unit": p.unit,
                "price": p.price,
                "desc": p.desc,
                "hsn_code": p.hsn_code or "",
            }
            for p in products
        ],
        "customers": [
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "city": c.city,
                "address": c.address,
                "gstin": c.gstin,
                "created_at": c.created_at,
                "store_images_json": c.store_images_json or "[]",
                "store_videos_json": c.store_videos_json or "[]",
                "store_width": c.store_width,
                "store_length": c.store_length,
                "store_height": c.store_height,
                "store_area": c.store_area,
            }
            for c in customers
        ],
        "quotations": [
            {
                "id": q.id,
                "quote_number": q.quote_number,
                "date": q.date,
                "customer_id": q.customer_id,
                "customer_name": q.customer_name,
                "customer_phone": q.customer_phone,
                "customer_email": q.customer_email,
                "customer_city": q.customer_city,
                "customer_address": q.customer_address,
                "customer_gstin": q.customer_gstin,
                "items_json": q.items_json,
                "gst_mode": q.gst_mode,
                "subtotal": q.subtotal,
                "delivery": q.delivery,
                "discount_percent": q.discount_percent,
                "discount_amount": q.discount_amount,
                "gst_rate": q.gst_rate,
                "gst_amount": q.gst_amount,
                "cgst": q.cgst,
                "sgst": q.sgst,
                "igst": q.igst,
                "grand_total": q.grand_total,
                "terms_json": q.terms_json,
                "validity_days": q.validity_days,
                "payment_type": q.payment_type,
                "status": q.status,
                "payment_status": q.payment_status,
                "created_at": q.created_at,
            }
            for q in quotations
        ],
        "payments": [
            {
                "id": pay.id,
                "quotation_id": pay.quotation_id,
                "customer_id": pay.customer_id,
                "invoice_number": pay.invoice_number,
                "payment_type": pay.payment_type,
                "amount": pay.amount,
                "payment_date": pay.payment_date,
                "payment_mode": pay.payment_mode,
                "transaction_id": pay.transaction_id or "",
                "remarks": pay.remarks or "",
                "created_by": pay.created_by or "Admin",
            }
            for pay in payments
        ],
        "leads": [
            {
                "id": l.id,
                "lead_number": l.lead_number,
                "salesman_id": l.salesman_id,
                "salesman_name": l.salesman_name or "",
                "customer_name": l.customer_name,
                "phone": l.phone or "",
                "shop_name": l.shop_name or "",
                "address": l.address or "",
                "city": l.city or "",
                "pincode": l.pincode or "",
                "business_type": l.business_type or "",
                "remarks": l.remarks or "",
                "follow_up_date": l.follow_up_date or "",
                "latitude": l.latitude,
                "longitude": l.longitude,
                "photo": l.photo or "",
                "store_images_json": l.store_images_json or "[]",
                "store_videos_json": l.store_videos_json or "[]",
                "store_width": l.store_width,
                "store_length": l.store_length,
                "store_height": l.store_height,
                "store_area": l.store_area,
                "status": l.status or "New Lead",
                "lead_source": l.lead_source or "Online",
                "facebook_lead_id": l.facebook_lead_id or "",
                "campaign_id": l.campaign_id or "",
                "campaign_name": l.campaign_name or "",
                "adset_id": l.adset_id or "",
                "adset_name": l.adset_name or "",
                "ad_id": l.ad_id or "",
                "ad_name": l.ad_name or "",
                "page_id": l.page_id or "",
                "form_id": l.form_id or "",
                "platform": l.platform or "",
                "assigned_to": l.assigned_to or "",
                "meta_created_time": l.meta_created_time or "",
                "sync_status": l.sync_status or "",
                "created_by": l.created_by or "",
                "current_owner": l.current_owner or "",
                "last_updated_by": l.last_updated_by or "",
                "created_note": l.created_note or "",
                "created_note_by": l.created_note_by or "",
                "created_note_date": l.created_note_date or "",
                "created_note_time": l.created_note_time or "",
                "created_at": l.created_at,
                "updated_at": l.updated_at,
            }
            for l in leads
        ],
        "lead_followups": [
            {
                "id": lf.id,
                "lead_id": lf.lead_id,
                "priority": lf.priority or "Medium",
                "follow_up_date": lf.follow_up_date or "",
                "follow_up_time": lf.follow_up_time or "",
                "status": lf.status or "Pending",
                "notes": lf.notes or "",
                "created_by_id": lf.created_by_id or "",
                "created_by_name": lf.created_by_name or "",
                "created_by": lf.created_by or "",
                "created_role": lf.created_role or "",
                "assigned_to": lf.assigned_to or "",
                "completed_date": lf.completed_date or "",
                "completed_at": lf.completed_at or 0,
                "completed_by": lf.completed_by or "",
                "created_at": lf.created_at,
                "updated_at": lf.updated_at,
            }
            for lf in lead_followups
        ],
    }

    # Audit log backup creation
    try:
        backup_audit = models.AuditLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            username=current_user.username,
            role=current_user.role,
            action="Database Backup",
            ip_address=request.client.host if request and request.client else "",
            timestamp=int(time.time() * 1000),
            details=f"Full database backup exported: {len(products)} products, {len(customers)} customers, {len(quotations)} quotations, {len(leads)} leads"
        )
        db.add(backup_audit)
        db.commit()
    except Exception as audit_err:
        logger.error(f"Failed to write backup audit log: {audit_err}")

    return result


@app.post("/restore")
def restore_backup(payload: dict, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user), request: Request = None):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    if "products" not in payload or "customers" not in payload or "quotations" not in payload:
        raise HTTPException(status_code=400, detail="Invalid backup format: missing products, customers, or quotations")

    try:
        # Clear tables in dependency order
        db.query(models.LeadFollowup).delete()
        db.query(models.LeadActivity).delete()
        db.query(models.FollowupHistory).delete()
        db.query(models.Lead).delete()
        db.query(models.Payment).delete()
        db.query(models.Quotation).delete()
        db.query(models.Customer).delete()
        db.query(models.Product).delete()
        db.commit()

        # Restore products with safe field mapping
        for p in payload["products"]:
            db.add(models.Product(
                id=p.get("id") or str(uuid.uuid4()),
                name=p.get("name", ""),
                category=p.get("category", ""),
                unit=p.get("unit", "per piece"),
                price=float(p.get("price", 0)),
                desc=p.get("desc", ""),
                hsn_code=p.get("hsn_code", "")
            ))

        # Restore customers with safe field mapping
        for c in payload["customers"]:
            db.add(models.Customer(
                id=c.get("id") or str(uuid.uuid4()),
                name=c.get("name", ""),
                phone=c.get("phone", ""),
                email=c.get("email", ""),
                city=c.get("city", ""),
                address=c.get("address", ""),
                gstin=c.get("gstin", ""),
                created_at=c.get("created_at", 0),
                store_images_json=c.get("store_images_json", "[]"),
                store_videos_json=c.get("store_videos_json", "[]"),
                store_width=c.get("store_width"),
                store_length=c.get("store_length"),
                store_height=c.get("store_height"),
                store_area=c.get("store_area"),
            ))

        # Restore quotations with safe field mapping
        for q in payload["quotations"]:
            db.add(models.Quotation(
                id=q.get("id") or str(uuid.uuid4()),
                quote_number=q.get("quote_number", ""),
                date=q.get("date", ""),
                customer_id=q.get("customer_id"),
                customer_name=q.get("customer_name", ""),
                customer_phone=q.get("customer_phone", ""),
                customer_email=q.get("customer_email", ""),
                customer_city=q.get("customer_city", ""),
                customer_address=q.get("customer_address", ""),
                customer_gstin=q.get("customer_gstin", ""),
                items_json=q.get("items_json", "[]"),
                gst_mode=q.get("gst_mode", "split"),
                subtotal=float(q.get("subtotal", 0)),
                delivery=float(q.get("delivery", 0)),
                discount_percent=float(q.get("discount_percent", 0)),
                discount_amount=float(q.get("discount_amount", 0)),
                gst_rate=float(q.get("gst_rate", 18)),
                gst_amount=float(q.get("gst_amount", 0)),
                cgst=float(q.get("cgst", 0)),
                sgst=float(q.get("sgst", 0)),
                igst=float(q.get("igst", 0)),
                grand_total=float(q.get("grand_total", 0)),
                terms_json=q.get("terms_json", "[]"),
                validity_days=int(q.get("validity_days", 15)),
                payment_type=q.get("payment_type", "advance_50"),
                status=q.get("status", "Draft"),
                payment_status=q.get("payment_status", "Pending"),
                created_at=q.get("created_at", 0),
            ))

        # Restore payments
        for pay in payload.get("payments", []):
            db.add(models.Payment(
                id=pay.get("id") or str(uuid.uuid4()),
                quotation_id=pay.get("quotation_id", ""),
                customer_id=pay.get("customer_id", ""),
                invoice_number=pay.get("invoice_number", ""),
                payment_type=pay.get("payment_type", ""),
                amount=float(pay.get("amount", 0)),
                payment_date=pay.get("payment_date", 0),
                payment_mode=pay.get("payment_mode", ""),
                transaction_id=pay.get("transaction_id", ""),
                remarks=pay.get("remarks", ""),
                created_by=pay.get("created_by", "Admin"),
            ))

        # Restore leads
        for l in payload.get("leads", []):
            db.add(models.Lead(
                id=l.get("id") or str(uuid.uuid4()),
                lead_number=l.get("lead_number", ""),
                salesman_id=l.get("salesman_id", ""),
                salesman_name=l.get("salesman_name", ""),
                customer_name=l.get("customer_name", ""),
                phone=l.get("phone", ""),
                shop_name=l.get("shop_name", ""),
                address=l.get("address", ""),
                city=l.get("city", ""),
                pincode=l.get("pincode", ""),
                business_type=l.get("business_type", ""),
                remarks=l.get("remarks", ""),
                follow_up_date=l.get("follow_up_date", ""),
                latitude=l.get("latitude"),
                longitude=l.get("longitude"),
                photo=l.get("photo", ""),
                store_images_json=l.get("store_images_json", "[]"),
                store_videos_json=l.get("store_videos_json", "[]"),
                store_width=l.get("store_width"),
                store_length=l.get("store_length"),
                store_height=l.get("store_height"),
                store_area=l.get("store_area"),
                status=l.get("status", "New Lead"),
                lead_source=l.get("lead_source", ""),
                facebook_lead_id=l.get("facebook_lead_id", ""),
                campaign_id=l.get("campaign_id", ""),
                campaign_name=l.get("campaign_name", ""),
                adset_id=l.get("adset_id", ""),
                adset_name=l.get("adset_name", ""),
                ad_id=l.get("ad_id", ""),
                ad_name=l.get("ad_name", ""),
                page_id=l.get("page_id", ""),
                form_id=l.get("form_id", ""),
                platform=l.get("platform", ""),
                assigned_to=l.get("assigned_to", ""),
                meta_created_time=l.get("meta_created_time", ""),
                sync_status=l.get("sync_status", ""),
                created_by=l.get("created_by", ""),
                current_owner=l.get("current_owner", ""),
                last_updated_by=l.get("last_updated_by", ""),
                created_note=l.get("created_note", ""),
                created_note_by=l.get("created_note_by", ""),
                created_note_date=l.get("created_note_date", ""),
                created_note_time=l.get("created_note_time", ""),
                created_at=l.get("created_at", 0),
                updated_at=l.get("updated_at", 0),
            ))

        # Restore lead followups
        for lf in payload.get("lead_followups", []):
            db.add(models.LeadFollowup(
                id=lf.get("id") or str(uuid.uuid4()),
                lead_id=lf.get("lead_id", ""),
                priority=lf.get("priority", "Medium"),
                follow_up_date=lf.get("follow_up_date", ""),
                follow_up_time=lf.get("follow_up_time", ""),
                status=lf.get("status", "Pending"),
                notes=lf.get("notes", ""),
                created_by_id=lf.get("created_by_id", ""),
                created_by_name=lf.get("created_by_name", ""),
                created_by=lf.get("created_by", ""),
                created_role=lf.get("created_role", ""),
                assigned_to=lf.get("assigned_to", ""),
                completed_date=lf.get("completed_date", ""),
                completed_at=lf.get("completed_at", 0),
                completed_by=lf.get("completed_by", ""),
                created_at=lf.get("created_at", 0),
                updated_at=lf.get("updated_at", 0),
            ))

        db.commit()

        # Audit log restore action
        try:
            restore_audit = models.AuditLog(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                username=current_user.username,
                role=current_user.role,
                action="Database Restore",
                ip_address=request.client.host if request and request.client else "",
                timestamp=int(time.time() * 1000),
                details=(
                    f"Database restore completed: "
                    f"{len(payload['products'])} products, "
                    f"{len(payload['customers'])} customers, "
                    f"{len(payload['quotations'])} quotations, "
                    f"{len(payload.get('leads', []))} leads, "
                    f"{len(payload.get('payments', []))} payments"
                )
            )
            db.add(restore_audit)
            db.commit()
        except Exception as audit_err:
            logger.error(f"Failed to write restore audit log: {audit_err}")

        return {
            "status": "success",
            "message": "Database restored successfully",
            "restored": {
                "products": len(payload["products"]),
                "customers": len(payload["customers"]),
                "quotations": len(payload["quotations"]),
                "payments": len(payload.get("payments", [])),
                "leads": len(payload.get("leads", [])),
                "lead_followups": len(payload.get("lead_followups", []))
            }
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Restore failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)

