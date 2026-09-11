import json
import logging
from sqlalchemy import Column, String, Float, Integer, Text, Boolean, BigInteger
from database import Base

logger = logging.getLogger(__name__)


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    desc = Column(Text, default="")
    hsn_code = Column(String, default="")
    manufacturing_materials_json = Column(Text, default="[]")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    phone = Column(String, default="", index=True)
    email = Column(String, default="")
    city = Column(String, default="")
    address = Column(String, default="")
    gstin = Column(String, default="")
    created_at = Column(BigInteger, default=0)
    store_images_json = Column(Text, default="[]")
    store_videos_json = Column(Text, default="[]")

    # Store measurements
    store_width = Column(Float, nullable=True)
    store_length = Column(Float, nullable=True)
    store_height = Column(Float, nullable=True)
    store_area = Column(Float, nullable=True)



class Quotation(Base):
    __tablename__ = "quotations"

    id = Column(String, primary_key=True, index=True)
    quote_number = Column(String, nullable=False, index=True, unique=True)
    date = Column(String, nullable=False)
    customer_id = Column(String, nullable=True, index=True)
    customer_name = Column(String, nullable=False, index=True)
    customer_phone = Column(String, default="", index=True)
    customer_email = Column(String, default="")
    customer_city = Column(String, default="")
    customer_address = Column(String, default="")
    customer_gstin = Column(String, default="")
    items_json = Column(Text, nullable=False)   # JSON array of line items
    gst_mode = Column(String, default="split")  # split | igst | none
    subtotal = Column(Float, default=0)
    delivery = Column(Float, default=0)
    discount_percent = Column(Float, default=0)
    discount_amount = Column(Float, default=0)
    gst_rate = Column(Float, default=18)
    gst_amount = Column(Float, default=0)
    cgst = Column(Float, default=0)
    sgst = Column(Float, default=0)
    igst = Column(Float, default=0)
    grand_total = Column(Float, default=0)
    terms_json = Column(Text, default="[]")     # JSON array of terms
    validity_days = Column(Integer, default=15)
    payment_type = Column(String, default="advance_50") # advance_50 | full_payment
    status = Column(String, default="Draft", index=True) # Draft | Approved | Advance Paid | Production | Ready for Delivery | Completed | Cancelled
    payment_status = Column(String, default="Pending") # Pending | Advance Paid | Partial Paid | Paid | Overdue
    gst_type = Column(String, default="exclusive")  # exclusive | inclusive
    gst_inclusive = Column(Boolean, default=False)
    created_at = Column(BigInteger, default=0, index=True)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, index=True)
    quotation_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)
    invoice_number = Column(String, nullable=False)
    payment_type = Column(String, nullable=False)  # Advance | Final | Full Payment
    amount = Column(Float, nullable=False)
    payment_date = Column(BigInteger, nullable=False, index=True)  # Epoch milliseconds
    payment_mode = Column(String, nullable=False)  # Cash | UPI | Bank Transfer | Cheque
    transaction_id = Column(String, default="")
    remarks = Column(String, default="")
    created_by = Column(String, default="Admin")


class AppSettings(Base):
    """Single-row key/value store for application-wide settings.
    
    Used rows:
      key='default_terms'  → JSON array of strings (Terms & Conditions)
      key='company_whatsapp'  → company WhatsApp number for salesman notifications
    """
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(Text, default="")


class Salesman(Base):
    """Salesman credentials and profile."""
    __tablename__ = "salesmen"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, default="", index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    pin = Column(String, nullable=False)          # 4-6 digit PIN (plain for now)
    area = Column(String, default="")             # territory / area
    active = Column(Boolean, default=True)
    created_at = Column(BigInteger, default=0)


class Telecaller(Base):
    """Telecaller credentials and profile."""
    __tablename__ = "telecallers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, default="", index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    pin = Column(String, nullable=False)          # 4-6 digit PIN (plain for now)
    active = Column(Boolean, default=True)
    created_at = Column(BigInteger, default=0)


class Lead(Base):
    """Sales leads — completely isolated from customers until converted."""
    __tablename__ = "leads"

    id = Column(String, primary_key=True, index=True)
    lead_number = Column(String, nullable=False, index=True)  # LD-0001
    salesman_id = Column(String, nullable=False, index=True)
    salesman_name = Column(String, default="")

    # Contact info
    customer_name = Column(String, nullable=False, index=True)
    phone = Column(String, default="", index=True)
    shop_name = Column(String, default="")
    address = Column(String, default="")
    city = Column(String, default="")
    pincode = Column(String, default="")
    business_type = Column(String, default="")    # Supermarket | Pharmacy | Garment | Other
    remarks = Column(Text, default="")

    # Follow-up
    follow_up_date = Column(String, default="", index=True)   # ISO date string YYYY-MM-DD

    # GPS
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Photo (base64 encoded)
    photo = Column(Text, default="")
    store_images_json = Column(Text, default="[]")
    store_videos_json = Column(Text, default="[]")

    # Store measurements
    store_width = Column(Float, nullable=True)
    store_length = Column(Float, nullable=True)
    store_height = Column(Float, nullable=True)
    store_area = Column(Float, nullable=True)


    # Status workflow
    status = Column(String, default="New Lead", index=True)   # New Lead | Contacted | Visited | Converted | Lost

    lead_source = Column(String, default="")      # Meta Ads | Website | Direct Walk-in | Manual Entry

    facebook_lead_id = Column(String, default="", index=True)
    campaign_id = Column(String, default="")
    campaign_name = Column(String, default="")
    adset_id = Column(String, default="")
    adset_name = Column(String, default="")
    ad_id = Column(String, default="")
    ad_name = Column(String, default="")
    page_id = Column(String, default="")
    form_id = Column(String, default="")
    platform = Column(String, default="")
    assigned_to = Column(String, default="", index=True)
    meta_created_time = Column(String, default="")
    sync_status = Column(String, default="")
    created_by = Column(String, default="", index=True)
    current_owner = Column(String, default="", index=True)
    last_updated_by = Column(String, default="")

    # Initial visit note — set once at lead creation, never overwritten
    created_note = Column(Text, default="")
    created_note_by = Column(String, default="")
    created_note_date = Column(String, default="")  # DD-MMM-YYYY
    created_note_time = Column(String, default="")  # HH:MM AM/PM

    created_at = Column(BigInteger, default=0, index=True)        # epoch ms
    updated_at = Column(BigInteger, default=0)        # epoch ms


class MetaFailedSync(Base):
    __tablename__ = "meta_failed_syncs"
    
    id = Column(String, primary_key=True, index=True)
    facebook_lead_id = Column(String, nullable=False, index=True)
    payload = Column(Text, nullable=False) # raw event dict as json string
    error_message = Column(Text, default="")
    attempts = Column(Integer, default=0)
    created_at = Column(BigInteger, default=0)


class LeadActivity(Base):
    __tablename__ = "lead_activities"

    id = Column(String, primary_key=True, index=True)
    lead_id = Column(String, nullable=False, index=True)
    lead_number = Column(String, default="", index=True)
    date = Column(String, nullable=False) # DD-MMM-YYYY
    time = Column(String, nullable=False) # HH:MM AM/PM
    username = Column(String, nullable=False)
    role = Column(String, nullable=False) # Salesman / Telecaller / Admin / System
    action = Column(String, nullable=False)
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    created_at = Column(BigInteger, default=0) # epoch ms


def log_lead_activity(db, lead_id: str, lead_number: str, username: str, role: str, action: str, old_val: str = "", new_val: str = ""):
    import uuid
    import time
    now_ms = int(time.time() * 1000)
    date_str = time.strftime("%d-%b-%Y")
    time_str = time.strftime("%I:%M %p")

    activity = LeadActivity(
        id=str(uuid.uuid4()),
        lead_id=lead_id,
        lead_number=lead_number,
        date=date_str,
        time=time_str,
        username=username,
        role=role,
        action=action,
        old_value=str(old_val) if old_val is not None else "",
        new_value=str(new_val) if new_val is not None else "",
        created_at=now_ms
    )
    db.add(activity)
    # Use flush() instead of commit() so the INSERT enters the current
    # transaction without acquiring a new SQLite write-lock each time.
    # The surrounding request handler commits once at the end.
    db.flush()
    return activity



class LeadFollowup(Base):
    __tablename__ = "lead_followups"

    id = Column(String, primary_key=True, index=True)
    lead_id = Column(String, nullable=False, index=True)
    priority = Column(String, default="Medium")  # Low | Medium | High | Urgent
    follow_up_date = Column(String, default="", index=True)   # ISO date YYYY-MM-DD
    follow_up_time = Column(String, default="")   # HH:MM AM/PM
    status = Column(String, default="Pending", index=True)    # Pending | Completed | Missed | Cancelled
    notes = Column(Text, default="")
    created_by_id = Column(String, default="")
    created_by_name = Column(String, default="")
    created_by = Column(String, default="")
    created_role = Column(String, default="")
    assigned_to = Column(String, default="", index=True)
    completed_date = Column(String, default="")
    completed_at = Column(BigInteger, default=0)
    completed_by = Column(String, default="")
    created_at = Column(BigInteger, default=0)
    updated_at = Column(BigInteger, default=0)


class FollowupHistory(Base):
    __tablename__ = "followup_histories"

    id = Column(String, primary_key=True, index=True)
    followup_id = Column(String, nullable=False, index=True)
    lead_id = Column(String, nullable=False, index=True)
    old_date = Column(String, default="")
    new_date = Column(String, default="")
    old_time = Column(String, default="")
    new_time = Column(String, default="")
    old_status = Column(String, default="")
    new_status = Column(String, default="")
    user = Column(String, default="")
    role = Column(String, default="")
    timestamp = Column(BigInteger, default=0)
    changed_by = Column(String, default="") # legacy
    changed_at = Column(BigInteger, default=0) # legacy
    date = Column(String, nullable=False) # DD-MMM-YYYY of update
    time = Column(String, nullable=False) # HH:MM AM/PM of update


class MetaIntegration(Base):
    __tablename__ = "meta_integrations"

    id = Column(String, primary_key=True, index=True)
    company_id = Column(String, default="")
    business_id = Column(String, default="")
    business_name = Column(String, default="")
    page_id = Column(String, default="")
    page_name = Column(String, default="")
    lead_form_id = Column(String, default="")
    lead_form_name = Column(String, default="")
    access_token = Column(String, default="")
    refresh_token = Column(String, default="")
    connected_at = Column(BigInteger, default=0)
    last_sync = Column(BigInteger, default=0)
    status = Column(String, default="Connected", index=True)


class TelecallerActivityLog(Base):
    __tablename__ = "telecaller_activity_logs"

    id = Column(String, primary_key=True, index=True)
    lead_id = Column(String, nullable=True, index=True)
    customer_id = Column(String, nullable=True, index=True)
    telecaller_id = Column(String, nullable=True, index=True)
    telecaller_name = Column(String, nullable=True)
    action_type = Column(String, nullable=False) # Call / WhatsApp / Remark / Follow-up / Status / Location / Photo
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    remark = Column(Text, default="")
    created_at = Column(BigInteger, default=0) # epoch ms


def log_telecaller_activity(db, lead_id: str, telecaller_name: str, action_type: str, old_value: str = "", new_value: str = "", remark: str = "", request=None):
    import uuid
    import time
    import json

    # 1. Resolve telecaller_id from name
    telecaller_id = ""
    if telecaller_name:
        tc = db.query(Telecaller).filter(Telecaller.name == telecaller_name).first()
        if tc:
            telecaller_id = tc.id

    # 2. Resolve customer_id from lead phone
    customer_id = ""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead and lead.phone:
        cust = db.query(Customer).filter(Customer.phone == lead.phone).first()
        if cust:
            customer_id = cust.id

    now_ms = int(time.time() * 1000)
    log_entry = TelecallerActivityLog(
        id=str(uuid.uuid4()),
        lead_id=lead_id or "",
        customer_id=customer_id or "",
        telecaller_id=telecaller_id or "",
        telecaller_name=telecaller_name or "",
        action_type=action_type,
        old_value=str(old_value) if old_value is not None else "",
        new_value=str(new_value) if new_value is not None else "",
        remark=str(remark) if remark is not None else "",
        created_at=now_ms
    )
    db.add(log_entry)
    db.flush()

    # Live updates via WebSocket
    if request:
        try:
            ws_manager = request.app.state.ws_manager
            if ws_manager:
                activity_data = {
                    "telecaller_name": telecaller_name,
                    "lead_id": lead_id,
                    "action_type": action_type
                }
                from websocket_manager import broadcast_event
                broadcast_event("telecaller_activity", activity_data)
        except Exception as e:
            logger.error(f"WebSocket broadcast failed: {e}")

    return log_entry


class SalesmanActivityLog(Base):
    __tablename__ = "salesman_activity_logs"

    id = Column(String, primary_key=True, index=True)
    lead_id = Column(String, nullable=True, index=True)
    salesman_id = Column(String, nullable=True, index=True)
    salesman_name = Column(String, nullable=True)
    activity_type = Column(String, nullable=False)   # Visit Created | Visit Completed | Visit Note | General Note | Shop Photo Uploaded | Follow-up Date Changed | Status Changed | Call Made | WhatsApp Opened | Location Captured
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    remark = Column(Text, default="")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(BigInteger, default=0) # epoch ms


def log_salesman_activity(db, lead_id: str, salesman_name: str, activity_type: str, old_value: str = "", new_value: str = "", remark: str = "", latitude: float = None, longitude: float = None, request=None):
    import uuid
    import time
    import json

    # Resolve salesman_id from name
    salesman_id = ""
    if salesman_name:
        sm = db.query(Salesman).filter(Salesman.name == salesman_name).first()
        if sm:
            salesman_id = sm.id

    now_ms = int(time.time() * 1000)
    log_entry = SalesmanActivityLog(
        id=str(uuid.uuid4()),
        lead_id=lead_id or "",
        salesman_id=salesman_id or "",
        salesman_name=salesman_name or "",
        activity_type=activity_type,
        old_value=str(old_value) if old_value is not None else "",
        new_value=str(new_value) if new_value is not None else "",
        remark=str(remark) if remark is not None else "",
        latitude=latitude,
        longitude=longitude,
        created_at=now_ms
    )
    db.add(log_entry)
    db.flush()

    # Live updates via WebSocket
    if request:
        try:
            ws_manager = request.app.state.ws_manager
            if ws_manager:
                activity_data = {
                    "salesman_name": salesman_name,
                    "lead_id": lead_id,
                    "activity_type": activity_type
                }
                from websocket_manager import broadcast_event
                broadcast_event("salesman_activity", activity_data)
                
                # Broadcast specific visit events
                lead = db.query(Lead).filter(Lead.id == lead_id).first()
                lead_salesman_id = lead.salesman_id if lead else ""
                lead_assigned_to = lead.assigned_to if lead else ""
                
                event_data = {
                    "lead_id": lead_id,
                    "salesman_id": lead_salesman_id,
                    "assigned_to": lead_assigned_to,
                    "salesman": salesman_name,
                    "activity_type": activity_type,
                    "remark": remark,
                    "latitude": latitude,
                    "longitude": longitude
                }
                
                if activity_type == "Visit Note":
                    broadcast_event("visit_note_added", event_data)
                elif activity_type in ["Visit Created", "Visit Completed", "Shop Photo Uploaded"]:
                    broadcast_event("visit_history_updated", event_data)
        except Exception as e:
            logger.error(f"WebSocket broadcast failed: {e}")

    return log_entry


class Admin(Base):
    __tablename__ = "admins"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True, index=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    ip_address = Column(String, default="")
    user_agent = Column(String, default="")
    last_login = Column(BigInteger, default=0)
    last_activity = Column(BigInteger, default=0)
    expires_at = Column(BigInteger, default=0, index=True)
    is_revoked = Column(Boolean, default=False, index=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    employee_id = Column(String, unique=True, nullable=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    mobile = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, index=True)  # admin | salesman | telecaller
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    last_login = Column(BigInteger, default=0)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(BigInteger, default=0)
    created_at = Column(BigInteger, default=0)
    updated_at = Column(BigInteger, default=0)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    username = Column(String, nullable=False)
    role = Column(String, nullable=False)
    action = Column(String, nullable=False)
    ip_address = Column(String, default="")
    timestamp = Column(BigInteger, default=0)
    details = Column(Text, default="")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    ip_address = Column(String, default="")
    timestamp = Column(BigInteger, default=0)
    success = Column(Boolean, default=False)


class RateLimit(Base):
    """Database-backed rate limiting for endpoints."""
    __tablename__ = "rate_limits"

    id = Column(String, primary_key=True, index=True)
    ip_address = Column(String, nullable=False, index=True)
    endpoint = Column(String, nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)


class PasswordResetOTP(Base):
    __tablename__ = "password_reset_otps"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    otp = Column(String, nullable=False)  # Stores bcrypt hash of 6-digit OTP
    expires_at = Column(BigInteger, nullable=False)  # Epoch milliseconds
    attempts = Column(Integer, default=0)
    is_used = Column(Boolean, default=False)
    created_at = Column(BigInteger, nullable=False)  # Epoch milliseconds


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=True, index=True)
    role = Column(String, nullable=True, index=True)
    message = Column(Text, nullable=False)
    type = Column(String, nullable=False, index=True)  # New Followup | Reminder | Followup Completed | Followup Overdue | Assignment Changed | Status Changed
    lead_id = Column(String, nullable=True, index=True)
    read = Column(Boolean, default=False)
    created_at = Column(BigInteger, default=0)


def create_notification(db, message: str, type: str, user_id: str = None, role: str = None, lead_id: str = None):
    import uuid
    import time
    from websocket_manager import broadcast_event

    now = int(time.time() * 1000)

    # Deduplicate: prevent identical notifications within the last 60 seconds
    # Strategy 1: If lead_id is set, deduplicate by (lead_id, type) within 1 minute
    if lead_id:
        existing = db.query(Notification).filter(
            Notification.lead_id == lead_id,
            Notification.type == type,
            Notification.created_at > (now - 60000)
        ).first()
        if existing:
            return existing
    else:
        # Strategy 2: For global/role notifications without a lead_id,
        # deduplicate by (user_id OR role, type, message) within 1 minute
        dup_filters = [
            Notification.type == type,
            Notification.message == message,
            Notification.created_at > (now - 60000),
        ]
        if user_id:
            dup_filters.append(Notification.user_id == user_id)
        elif role:
            dup_filters.append(Notification.role == role)

        existing = db.query(Notification).filter(*dup_filters).first()
        if existing:
            return existing

    notif = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        role=role,
        message=message,
        type=type,
        lead_id=lead_id,
        read=False,
        created_at=now
    )
    db.add(notif)
    db.flush()

    notif_data = {
        "id": notif.id,
        "user_id": notif.user_id,
        "role": notif.role,
        "message": notif.message,
        "type": notif.type,
        "lead_id": notif.lead_id,
        "read": notif.read,
        "created_at": notif.created_at
    }
    broadcast_event("notification_created", notif_data)
    return notif


class QuotationTerm(Base):
    __tablename__ = "quotation_terms"

    id = Column(String, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)


class QuotationMaterial(Base):
    __tablename__ = "quotation_materials"

    id = Column(String, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)


class QuotationBank(Base):
    __tablename__ = "quotation_banks"

    id = Column(String, primary_key=True, index=True)
    bank_name = Column(String, nullable=False)
    account_holder = Column(String, nullable=False)
    account_number = Column(String, nullable=False)
    ifsc_code = Column(String, nullable=False)
    branch = Column(String, default="")
    display_order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)


class QuotationSocial(Base):
    __tablename__ = "quotation_socials"

    id = Column(String, primary_key=True, index=True)
    platform = Column(String, nullable=False) # WhatsApp, Instagram, Facebook, YouTube, LinkedIn, Website
    icon = Column(String, default="")
    qr_code_url = Column(String, default="")
    cta_text = Column(String, default="")
    display_order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)


class QuotationWhyChoose(Base):
    __tablename__ = "quotation_why_chooses"

    id = Column(String, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)


class QuotationService(Base):
    __tablename__ = "quotation_services"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    display_order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)


class QuotationFooter(Base):
    __tablename__ = "quotation_footers"

    id = Column(String, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    is_enabled = Column(Boolean, default=True)


# ── MANUFACTURING & PRODUCTION ERP MODELS ────────────────────────────────────

class ProductionOrder(Base):
    """Manufacturing Production Order model generated automatically after payment receipt."""
    __tablename__ = "production_orders"

    id = Column(String, primary_key=True, index=True)
    production_number = Column(String, nullable=False, index=True, unique=True)  # RF-PO-2026-00001
    quotation_id = Column(String, nullable=False, index=True)
    quote_number = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=True, index=True)
    customer_name = Column(String, nullable=False, index=True)
    mobile = Column(String, default="", index=True)
    address = Column(Text, default="")
    payment_status = Column(String, default="Paid")  # Advance Paid | Paid | Partial Paid
    priority = Column(String, default="Medium", index=True)  # Low | Medium | High | Urgent
    order_date = Column(BigInteger, default=0, index=True)  # Epoch ms
    expected_dispatch = Column(String, default="", index=True)  # YYYY-MM-DD
    sales_person = Column(String, default="")
    status = Column(String, default="Pending", index=True)  # Pending | Accepted | In Production | Quality Check | Packing | Ready for Dispatch | Completed | Rejected | Cancelled
    current_stage = Column(String, default="Pending", index=True)  # Pending | Accepted | Material Issued | Cutting | Fabrication | Welding | Grinding | Powder Coating | Assembly | Quality Check | Packing | Ready for Dispatch | Completed
    customer_notes = Column(Text, default="")
    quotation_remarks = Column(Text, default="")
    sales_instructions = Column(Text, default="")
    created_at = Column(BigInteger, default=0, index=True)
    updated_at = Column(BigInteger, default=0)


class ProductionItem(Base):
    """Individual product item within a production order copied from quotation."""
    __tablename__ = "production_items"

    id = Column(String, primary_key=True, index=True)
    production_order_id = Column(String, nullable=False, index=True)
    product_id = Column(String, nullable=True, index=True)
    product_name = Column(String, nullable=False)
    product_description = Column(Text, default="")
    hsn = Column(String, default="")
    quantity = Column(Float, default=1.0)
    unit = Column(String, default="Pcs")
    product_image = Column(Text, default="")
    remarks = Column(Text, default="")


class ProductionStatusHistory(Base):
    """Detailed stage history tracking start, end time, performer, and stage notes."""
    __tablename__ = "production_status_histories"

    id = Column(String, primary_key=True, index=True)
    production_order_id = Column(String, nullable=False, index=True)
    stage_name = Column(String, nullable=False, index=True)  # Pending | Accepted | Material Issued | Cutting | Fabrication | Welding | Grinding | Powder Coating | Assembly | Quality Check | Packing | Ready for Dispatch | Completed
    status = Column(String, default="Pending")  # Pending | In Progress | Completed | Paused | Skipped
    start_time = Column(BigInteger, default=0)
    end_time = Column(BigInteger, default=0)
    completed_by = Column(String, default="")
    remarks = Column(Text, default="")
    created_at = Column(BigInteger, default=0)


class ProductionWorker(Base):
    """Workers assigned to specific roles on a production order."""
    __tablename__ = "production_workers"

    id = Column(String, primary_key=True, index=True)
    production_order_id = Column(String, nullable=False, index=True)
    worker_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # Supervisor | Fabricator | Welder | Painter | Assembler | Packing Staff
    assigned_at = Column(BigInteger, default=0)
    assigned_by = Column(String, default="Factory Manager")


class ProductionNote(Base):
    """Notes and comments recorded on production orders."""
    __tablename__ = "production_notes"

    id = Column(String, primary_key=True, index=True)
    production_order_id = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(BigInteger, default=0)


class ProductionAttachment(Base):
    """Documents and images attached to production orders."""
    __tablename__ = "production_attachments"

    id = Column(String, primary_key=True, index=True)
    production_order_id = Column(String, nullable=False, index=True)
    file_name = Column(String, nullable=False)
    file_type = Column(String, default="General")  # Quotation PDF | Store Layout | Rack Drawing | Product Image | General
    file_url = Column(Text, nullable=False)
    uploaded_at = Column(BigInteger, default=0)


# ── INVENTORY & RAW MATERIAL ERP MODELS ──────────────────────────────────────

class RawMaterial(Base):
    """Raw material stock inventory item."""
    __tablename__ = "raw_materials"

    id = Column(String, primary_key=True, index=True)
    material_code = Column(String, nullable=False, unique=True, index=True)  # RM-CRS-001
    name = Column(String, nullable=False, index=True)  # CR Sheet, MS Pipe, Angle, Shelf, Nut Bolt, Paint, Powder, Plastic Leveler, Accessories
    category = Column(String, default="General", index=True)  # Sheet Metal | Pipe & Tube | Hardware | Coating & Paint | Accessories
    unit = Column(String, default="Pcs")  # Sheet | Meter | Kg | Pcs | Box | Liter
    current_stock = Column(Float, default=0.0)
    reserved_stock = Column(Float, default=0.0)
    minimum_level = Column(Float, default=10.0)
    reorder_quantity = Column(Float, default=50.0)
    unit_cost = Column(Float, default=0.0)
    location = Column(String, default="Main Factory Warehouse")
    created_at = Column(BigInteger, default=0)
    updated_at = Column(BigInteger, default=0)


class ProductionMaterialRequirement(Base):
    """Calculated raw material requirements for a production order."""
    __tablename__ = "production_material_requirements"

    id = Column(String, primary_key=True, index=True)
    production_order_id = Column(String, nullable=False, index=True)
    material_id = Column(String, nullable=False, index=True)
    material_name = Column(String, nullable=False)
    material_description = Column(Text, default="")
    required_qty = Column(Float, default=0.0)
    reserved_qty = Column(Float, default=0.0)
    deducted_qty = Column(Float, default=0.0)
    unit = Column(String, default="Pcs")
    status = Column(String, default="Reserved")  # Reserved | Issued | Insufficient  (INVENTORY tracking — do not mix with manufacturing)
    created_at = Column(BigInteger, default=0)
    # Manufacturing progress tracking (SEPARATE from inventory allocation)
    prepared_qty = Column(Float, default=0.0)           # How much factory has actually prepared/produced
    manufacturing_status = Column(String, default="Pending")  # Pending | In Progress | Completed


class InventoryTransaction(Base):
    """Audit log of stock movements (In, Reserved, Released, Issued/Deducted)."""
    __tablename__ = "inventory_transactions"

    id = Column(String, primary_key=True, index=True)
    material_id = Column(String, nullable=False, index=True)
    material_name = Column(String, nullable=False)
    type = Column(String, nullable=False, index=True)  # Stock In | Reserved | Released | Deducted | Adjustment
    qty = Column(Float, nullable=False)
    reference_id = Column(String, default="")  # Production Order ID / Purchase Request ID
    remarks = Column(Text, default="")
    created_by = Column(String, default="System")
    created_at = Column(BigInteger, default=0, index=True)


class PurchaseRequest(Base):
    """Auto-generated purchase requests when stock reaches minimum levels or is insufficient."""
    __tablename__ = "purchase_requests"

    id = Column(String, primary_key=True, index=True)
    request_number = Column(String, nullable=False, unique=True, index=True)  # PR-2026-00001
    production_order_id = Column(String, default="")
    material_id = Column(String, nullable=False, index=True)
    material_name = Column(String, nullable=False)
    requested_qty = Column(Float, nullable=False)
    unit = Column(String, default="Pcs")
    status = Column(String, default="Pending", index=True)  # Pending | Approved | Ordered | Fulfilled | Cancelled
    reason = Column(Text, default="")
    created_by = Column(String, default="System")
    created_at = Column(BigInteger, default=0, index=True)








