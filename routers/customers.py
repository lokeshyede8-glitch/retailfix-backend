import uuid
import time
import re
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from database import get_db
import models
import schemas
from auth_utils import get_current_user, RoleChecker, CurrentUser, normalize_phone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=List[schemas.CustomerOut])
def list_customers(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    t0 = time.perf_counter()

    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "salesman", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    if role_lower == "salesman":
        # Single JOIN query — no intermediate phone list fetch
        customers = (
            db.query(models.Customer)
            .join(models.Lead, models.Customer.phone == models.Lead.phone)
            .filter(
                models.Lead.salesman_id == current_user.id,
                models.Customer.phone != ""
            )
            .distinct()
            .order_by(models.Customer.name.asc())
            .all()
        )
    elif role_lower == "telecaller":
        # Single JOIN query for telecaller
        customers = (
            db.query(models.Customer)
            .join(models.Lead, models.Customer.phone == models.Lead.phone)
            .filter(
                (
                    (models.Lead.assigned_to == current_user.username) |
                    (models.Lead.current_owner == current_user.username)
                ),
                models.Customer.phone != ""
            )
            .distinct()
            .order_by(models.Customer.name.asc())
            .all()
        )
    else:
        customers = db.query(models.Customer).order_by(models.Customer.name.asc()).all()

    # ── Single aggregated query replaces N per-customer quotation fetches ────
    # Returns (customer_id, count, total_revenue, max_created_at)
    agg_rows = (
        db.query(
            models.Quotation.customer_id,
            func.count(models.Quotation.id).label("total_quotes"),
            func.sum(models.Quotation.grand_total).label("total_revenue"),
            func.max(models.Quotation.created_at).label("latest_at"),
        )
        .group_by(models.Quotation.customer_id)
        .all()
    )
    agg = {r.customer_id: r for r in agg_rows}

    # We still need the date string for the latest quotation per customer,
    # but only for customers that have quotes.  One extra query for just the
    # date column is far cheaper than pulling all Quotation objects.
    latest_dates_raw = (
        db.query(
            models.Quotation.customer_id,
            models.Quotation.date,
            models.Quotation.created_at,
        )
        .order_by(models.Quotation.created_at.desc())
        .all()
    )
    # Keep only the first (newest) date per customer
    latest_date: dict[str, str] = {}
    for row in latest_dates_raw:
        if row.customer_id not in latest_date:
            latest_date[row.customer_id] = row.date

    for c in customers:
        row = agg.get(c.id)
        if row:
            c.total_quotes = row.total_quotes
            c.total_revenue = float(row.total_revenue or 0)
            c.last_quote_date = latest_date.get(c.id)
        else:
            c.total_quotes = 0
            c.total_revenue = 0.0
            c.last_quote_date = None

    logger.info("GET /customers  rows=%d  %.0fms", len(customers), (time.perf_counter() - t0) * 1000)
    return customers


def validate_customer(payload: schemas.CustomerCreate, db: Session, customer_id: str = None):
    # Name validation
    name_val = payload.name.strip() if payload.name else ""
    if not name_val:
        raise HTTPException(status_code=400, detail="Customer name cannot be empty")

    # Duplicate check by name
    query = db.query(models.Customer).filter(func.lower(models.Customer.name) == func.lower(name_val))
    if customer_id:
        query = query.filter(models.Customer.id != customer_id)
    if query.first():
        raise HTTPException(status_code=400, detail=f"Customer with name '{name_val}' already exists")

    # Phone validation
    phone_val = payload.phone.strip() if payload.phone else ""
    if phone_val:
        numeric_phone = re.sub(r"[^0-9]", "", phone_val)
        if len(numeric_phone) < 10 or len(numeric_phone) > 12:
            raise HTTPException(status_code=400, detail="Phone number must be between 10 to 12 digits")

        # Duplicate check by phone
        norm_phone = normalize_phone(phone_val)
        if norm_phone:
            phone_query = db.query(models.Customer).filter(models.Customer.phone == norm_phone)
            if customer_id:
                phone_query = phone_query.filter(models.Customer.id != customer_id)
            if phone_query.first():
                raise HTTPException(status_code=400, detail=f"Customer with phone number '{phone_val}' already exists")

    # Email validation
    email_val = payload.email.strip() if payload.email else ""
    if email_val:
        email_regex = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
        if not re.match(email_regex, email_val):
            raise HTTPException(status_code=400, detail="Invalid email address format")

    # GSTIN validation
    gstin_val = payload.gstin.strip() if payload.gstin else ""
    if gstin_val:
        if len(gstin_val) != 15:
            raise HTTPException(status_code=400, detail="GSTIN must be exactly 15 characters long")


@router.post("", response_model=schemas.CustomerOut, status_code=201)
def create_customer(payload: schemas.CustomerCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role.lower() not in ["admin", "salesman", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    validate_customer(payload, db)

    customer = models.Customer(
        id=str(uuid.uuid4()),
        name=payload.name.strip(),
        phone=normalize_phone(payload.phone) if payload.phone else "",
        email=payload.email.strip() if payload.email else "",
        city=payload.city.strip() if payload.city else "",
        address=payload.address.strip() if payload.address else "",
        gstin=payload.gstin.strip() if payload.gstin else "",
        store_images_json=payload.store_images_json or "[]",
        store_videos_json=payload.store_videos_json or "[]",
        store_width=payload.store_width,
        store_length=payload.store_length,
        store_height=payload.store_height,
        store_area=payload.store_area,
        created_at=int(time.time() * 1000)
    )

    db.add(customer)
    db.commit()
    db.refresh(customer)
    
    cust_data = {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "city": customer.city,
        "address": customer.address,
        "gstin": customer.gstin,
        "store_images_json": customer.store_images_json,
        "store_videos_json": customer.store_videos_json,
        "store_width": customer.store_width,
        "store_length": customer.store_length,
        "store_height": customer.store_height,
        "store_area": customer.store_area,
        "created_at": customer.created_at
    }

    from websocket_manager import broadcast_event
    broadcast_event("customer_created", cust_data)
    
    return customer


@router.get("/{customer_id}", response_model=schemas.CustomerOut)
def get_customer(customer_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "salesman", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == customer.phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif role_lower == "telecaller":
        lead = db.query(models.Lead).filter(
            (models.Lead.assigned_to == current_user.username) |
            (models.Lead.current_owner == current_user.username),
            models.Lead.phone == customer.phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="Forbidden")

    agg = db.query(
        func.count(models.Quotation.id).label("total_quotes"),
        func.sum(models.Quotation.grand_total).label("total_revenue")
    ).filter(models.Quotation.customer_id == customer.id).first()

    latest_quote = db.query(models.Quotation.date).filter(
        models.Quotation.customer_id == customer.id
    ).order_by(models.Quotation.created_at.desc()).first()

    customer.total_quotes = agg.total_quotes or 0
    customer.total_revenue = float(agg.total_revenue or 0)
    customer.last_quote_date = latest_quote.date if latest_quote else None

    return customer


@router.get("/{customer_id}/history")
def get_customer_history(customer_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "salesman", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Access control
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == customer.phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif role_lower == "telecaller":
        lead = db.query(models.Lead).filter(
            (models.Lead.assigned_to == current_user.username) |
            (models.Lead.current_owner == current_user.username),
            models.Lead.phone == customer.phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        lead = db.query(models.Lead).filter(models.Lead.phone == customer.phone).first()

    followups = []
    followup_history = []
    activities = []
    telecaller_logs = []
    salesman_logs = []

    if lead:
        followups = db.query(models.LeadFollowup).filter(models.LeadFollowup.lead_id == lead.id).order_by(models.LeadFollowup.created_at.desc()).all()
        followup_history = db.query(models.FollowupHistory).filter(models.FollowupHistory.lead_id == lead.id).order_by(models.FollowupHistory.timestamp.desc()).all()
        activities = db.query(models.LeadActivity).filter(models.LeadActivity.lead_id == lead.id).order_by(models.LeadActivity.created_at.desc()).all()
        telecaller_logs = db.query(models.TelecallerActivityLog).filter(models.TelecallerActivityLog.lead_id == lead.id).order_by(models.TelecallerActivityLog.created_at.desc()).all()
        salesman_logs = db.query(models.SalesmanActivityLog).filter(models.SalesmanActivityLog.lead_id == lead.id).order_by(models.SalesmanActivityLog.created_at.desc()).all()

    return {
        "lead": {
            "id": lead.id,
            "lead_number": lead.lead_number,
            "status": lead.status,
            "lead_source": lead.lead_source,
            "assigned_to": lead.assigned_to,
            "salesman_name": lead.salesman_name,
            "current_owner": lead.current_owner,
            "remarks": lead.remarks,
            "created_note": lead.created_note,
            "created_note_by": lead.created_note_by,
            "created_note_date": lead.created_note_date,
            "created_note_time": lead.created_note_time,
            "business_type": lead.business_type,
            "pincode": lead.pincode,
        } if lead else None,
        "followups": [
            {
                "id": f.id,
                "priority": f.priority,
                "follow_up_date": f.follow_up_date,
                "follow_up_time": f.follow_up_time,
                "status": f.status,
                "notes": f.notes,
                "created_by_name": f.created_by_name,
                "assigned_to": f.assigned_to,
                "completed_date": f.completed_date,
                "completed_by": f.completed_by,
                "created_at": f.created_at,
            } for f in followups
        ],
        "followup_history": [
            {
                "id": fh.id,
                "old_date": fh.old_date,
                "new_date": fh.new_date,
                "old_time": fh.old_time,
                "new_time": fh.new_time,
                "old_status": fh.old_status,
                "new_status": fh.new_status,
                "user": fh.user,
                "role": fh.role,
                "timestamp": fh.timestamp,
                "date": fh.date,
                "time": fh.time,
            } for fh in followup_history
        ],
        "activities": [
            {
                "id": act.id,
                "date": act.date,
                "time": act.time,
                "username": act.username,
                "role": act.role,
                "action": act.action,
                "old_value": act.old_value,
                "new_value": act.new_value,
                "created_at": act.created_at,
            } for act in activities
        ],
        "telecaller_logs": [
            {
                "id": tl.id,
                "telecaller_name": tl.telecaller_name,
                "action_type": tl.action_type,
                "old_value": tl.old_value,
                "new_value": tl.new_value,
                "remark": tl.remark,
                "created_at": tl.created_at,
            } for tl in telecaller_logs
        ],
        "salesman_logs": [
            {
                "id": sl.id,
                "salesman_name": sl.salesman_name,
                "activity_type": sl.activity_type,
                "old_value": sl.old_value,
                "new_value": sl.new_value,
                "remark": sl.remark,
                "latitude": sl.latitude,
                "longitude": sl.longitude,
                "created_at": sl.created_at,
            } for sl in salesman_logs
        ]
    }


@router.put("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(customer_id: str, payload: schemas.CustomerUpdate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "salesman", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == customer.phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to update this customer")
    elif role_lower == "telecaller":
        lead = db.query(models.Lead).filter(
            (models.Lead.assigned_to == current_user.username) | 
            (models.Lead.current_owner == current_user.username),
            models.Lead.phone == customer.phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to update this customer")

    validate_customer(payload, db, customer_id)

    for field, value in payload.model_dump().items():
        if field == "phone":
            value = normalize_phone(value) if value else ""
        elif isinstance(value, str):
            value = value.strip()
        setattr(customer, field, value)

    db.commit()
    db.refresh(customer)
    
    cust_data = {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "city": customer.city,
        "address": customer.address,
        "gstin": customer.gstin,
        "store_images_json": customer.store_images_json,
        "store_videos_json": customer.store_videos_json,
        "store_width": customer.store_width,
        "store_length": customer.store_length,
        "store_height": customer.store_height,
        "store_area": customer.store_area,
        "created_at": customer.created_at
    }

    from websocket_manager import broadcast_event
    broadcast_event("customer_updated", cust_data)
    
    return customer


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    c_id = customer.id
    
    # Logical cascade delete for related payments and quotations
    db.query(models.Payment).filter(models.Payment.customer_id == customer_id).delete()
    db.query(models.Quotation).filter(models.Quotation.customer_id == customer_id).delete()
    
    db.delete(customer)
    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("customer_deleted", {"id": c_id})

