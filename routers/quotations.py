import json
import uuid
import time
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from auth_utils import get_current_user, RoleChecker, CurrentUser, normalize_phone

router = APIRouter(prefix="/quotations", tags=["Quotations"])


import logging
logger = logging.getLogger(__name__)

def _db_to_out(q: models.Quotation) -> schemas.QuotationOut:
    items = []
    if q.items_json:
        try:
            parsed_items = json.loads(q.items_json)
            if isinstance(parsed_items, list):
                for it in parsed_items:
                    if isinstance(it, dict):
                        items.append(schemas.LineItem(**it))
        except Exception as e:
            logger.warning(f"Error parsing items_json for quotation {q.id}: {e}")

    terms = []
    if q.terms_json:
        try:
            parsed_terms = json.loads(q.terms_json)
            if isinstance(parsed_terms, list):
                terms = [str(t) for t in parsed_terms if t is not None]
        except Exception as e:
            logger.warning(f"Error parsing terms_json for quotation {q.id}: {e}")

    return schemas.QuotationOut(
        id=q.id,
        quote_number=q.quote_number,
        date=q.date or "",
        customer_id=q.customer_id,
        customer=schemas.CustomerInfo(
            name=q.customer_name or "",
            phone=q.customer_phone or "",
            email=q.customer_email or "",
            city=q.customer_city or "",
            address=q.customer_address or "",
            gstin=q.customer_gstin or "",
        ),
        items=items,
        gst_mode=q.gst_mode or "split",
        totals=schemas.Totals(
            subtotal=q.subtotal or 0.0,
            delivery=q.delivery or 0.0,
            discount_percent=q.discount_percent or 0.0,
            discount_amount=q.discount_amount or 0.0,
            gst_rate=q.gst_rate or 18.0,
            gst_amount=q.gst_amount or 0.0,
            cgst=q.cgst or 0.0,
            sgst=q.sgst or 0.0,
            igst=q.igst or 0.0,
            grand_total=q.grand_total or 0.0,
            gst_type=q.gst_type or "exclusive",
            gst_inclusive=q.gst_inclusive or False,
        ),
        terms=terms,
        validity_days=q.validity_days or 15,
        payment_type=q.payment_type or "advance_50",
        status=q.status or "Draft",
        payment_status=q.payment_status or "Pending",
        gst_type=q.gst_type or "exclusive",
        gst_inclusive=q.gst_inclusive or False,
        created_at=q.created_at or 0,
    )


import datetime

def get_calculated_next_number(db: Session) -> str:
    year = datetime.datetime.now().year
    prefix = f"RF-Q-{year}-"
    # Select the maximum quote number lexicographically (which aligns with sequential padding)
    max_quote = db.query(models.Quotation.quote_number).filter(
        models.Quotation.quote_number.like(f"{prefix}%")
    ).order_by(models.Quotation.quote_number.desc()).first()
    
    max_seq = 0
    if max_quote:
        try:
            suffix_str = max_quote[0].replace(prefix, "")
            max_seq = int(suffix_str)
        except Exception:
            pass
    next_seq = max_seq + 1
    return f"{prefix}{next_seq:04d}"


@router.get("/next-number")
def get_next_quotation_number(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role.lower() == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    next_number = get_calculated_next_number(db)
    return {"next_number": next_number}


@router.get("", response_model=List[schemas.QuotationOut])
def list_quotations(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    if role_lower == "salesman":
        leads = db.query(models.Lead).filter(models.Lead.salesman_id == current_user.id).all()
        normalized_lead_phones = set()
        for l in leads:
            if l.phone:
                norm = normalize_phone(l.phone)
                if norm:
                    normalized_lead_phones.add(norm)
        
        all_quotes = db.query(models.Quotation).order_by(models.Quotation.created_at.desc()).all()
        rows = [
            q for q in all_quotes
            if q.customer_phone and normalize_phone(q.customer_phone) in normalized_lead_phones
        ]
    else:
        rows = db.query(models.Quotation).order_by(models.Quotation.created_at.desc()).all()
    return [_db_to_out(r) for r in rows]


@router.get("/{quote_id}", response_model=schemas.QuotationOut)
def get_quotation(quote_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to access this quotation")
    return _db_to_out(q)


@router.post("", response_model=schemas.QuotationOut, status_code=201)
def save_quotation(payload: schemas.QuotationCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    # Check for duplicate quote number
    existing = db.query(models.Quotation).filter(models.Quotation.quote_number == payload.quote_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Quotation with number '{payload.quote_number}' already exists")
        
    if role_lower == "salesman":
        phone = normalize_phone(payload.customer.phone) if payload.customer.phone else ""
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to generate quotations for this lead/customer")
            
    t = payload.totals
    q = models.Quotation(
        id=str(uuid.uuid4()),
        quote_number=payload.quote_number,
        date=payload.date,
        customer_id=payload.customer_id,
        customer_name=payload.customer.name,
        customer_phone=normalize_phone(payload.customer.phone) if payload.customer.phone else "",
        customer_email=payload.customer.email or "",
        customer_city=payload.customer.city or "",
        customer_address=payload.customer.address or "",
        customer_gstin=payload.customer.gstin or "",
        items_json=json.dumps([it.model_dump() for it in payload.items]),
        gst_mode=payload.gst_mode,
        subtotal=t.subtotal,
        delivery=t.delivery,
        discount_percent=t.discount_percent,
        discount_amount=t.discount_amount,
        gst_rate=t.gst_rate,
        gst_amount=t.gst_amount,
        cgst=t.cgst,
        sgst=t.sgst,
        igst=t.igst,
        grand_total=t.grand_total,
        terms_json=json.dumps(payload.terms),
        validity_days=payload.validity_days or 15,
        payment_type=payload.payment_type or "advance_50",
        status=payload.status or "Draft",
        payment_status=payload.payment_status or "Pending",
        gst_type=payload.gst_type or "exclusive",
        gst_inclusive=payload.gst_inclusive or False,
        created_at=int(time.time() * 1000),
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    # Look for matching lead by customer phone to link quotation event
    if q.customer_phone:
        lead = db.query(models.Lead).filter(models.Lead.phone == q.customer_phone).first()
        if lead:
            from models import log_lead_activity
            log_lead_activity(db, lead.id, lead.lead_number, "System", "System", "Quotation Generated", "", f"Quote No: {q.quote_number}, Total: {q.grand_total}")

    out_quote = _db_to_out(q)
    from websocket_manager import broadcast_event
    broadcast_event("quotation_created", out_quote.model_dump())
    
    return out_quote


@router.put("/{quote_id}/status", response_model=schemas.QuotationOut)
def update_quotation_status(quote_id: str, payload: dict, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to update this quotation")
    
    status = payload.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="Status not specified")
        
    q.status = status
    db.commit()
    db.refresh(q)
    
    out_quote = _db_to_out(q)
    from websocket_manager import broadcast_event
    broadcast_event("quotation_updated", out_quote.model_dump())
    
    return out_quote


@router.put("/{quote_id}/payment-options", response_model=schemas.QuotationOut)
def update_quotation_payment_options(quote_id: str, payload: dict, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to update this quotation")
        
    payment_type = payload.get("payment_type")
    if not payment_type:
        raise HTTPException(status_code=400, detail="Payment type not specified")
        
    q.payment_type = payment_type
    
    # Also update payment status if needed
    if payment_type == "full_payment":
        all_payments = db.query(models.Payment).filter(models.Payment.quotation_id == q.id).all()
        total_paid = sum(p.amount for p in all_payments)
        if total_paid >= q.grand_total:
            q.status = "Completed"
            q.payment_status = "Paid"
            
    db.commit()
    db.refresh(q)
    
    out_quote = _db_to_out(q)
    from websocket_manager import broadcast_event
    broadcast_event("quotation_updated", out_quote.model_dump())
    
    return out_quote


@router.delete("/{quote_id}", status_code=204)
def delete_quotation(quote_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    logger.info("Admin '%s' attempting to delete quotation '%s'", current_user.username, quote_id)
    from sqlalchemy import or_
    q = db.query(models.Quotation).filter(
        or_(models.Quotation.id == quote_id, models.Quotation.quote_number == quote_id)
    ).first()
    if not q:
        logger.warning("Quotation '%s' not found for deletion by admin '%s'", quote_id, current_user.username)
        raise HTTPException(status_code=404, detail="Quotation not found")
    q_id = q.id
    
    # Logical cascade delete for payments associated with this quotation
    db.query(models.Payment).filter(models.Payment.quotation_id == q_id).delete()
    
    db.delete(q)
    db.commit()
    logger.info("Quotation '%s' (ID: %s) successfully deleted by admin '%s'", q.quote_number, q_id, current_user.username)
    
    from websocket_manager import broadcast_event
    broadcast_event("quotation_deleted", {"id": q_id})


@router.put("/{quote_id}", response_model=schemas.QuotationOut)
def update_quotation(quote_id: str, payload: schemas.QuotationCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to modify this quotation")
            
        # Ensure updated customer details belong to assigned lead
        phone = normalize_phone(payload.customer.phone) if payload.customer.phone else ""
        lead_check = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == phone
        ).first()
        if not lead_check:
            raise HTTPException(status_code=403, detail="You do not have permission to generate quotations for this lead/customer")

    # Update fields
    q.date = payload.date
    q.customer_id = payload.customer_id
    q.customer_name = payload.customer.name
    q.customer_phone = normalize_phone(payload.customer.phone) if payload.customer.phone else ""
    q.customer_email = payload.customer.email or ""
    q.customer_city = payload.customer.city or ""
    q.customer_address = payload.customer.address or ""
    q.customer_gstin = payload.customer.gstin or ""
    q.items_json = json.dumps([it.model_dump() for it in payload.items])
    q.gst_mode = payload.gst_mode
    
    t = payload.totals
    q.subtotal = t.subtotal
    q.delivery = t.delivery
    q.discount_percent = t.discount_percent
    q.discount_amount = t.discount_amount
    q.gst_rate = t.gst_rate
    q.gst_amount = t.gst_amount
    q.cgst = t.cgst
    q.sgst = t.sgst
    q.igst = t.igst
    q.grand_total = t.grand_total
    q.terms_json = json.dumps(payload.terms)
    q.validity_days = payload.validity_days or 15
    q.payment_type = payload.payment_type or "advance_50"
    q.status = payload.status or q.status
    q.payment_status = payload.payment_status or q.payment_status
    q.gst_type = payload.gst_type or "exclusive"
    q.gst_inclusive = payload.gst_inclusive or False
    
    db.commit()
    db.refresh(q)
    
    out_quote = _db_to_out(q)
    from websocket_manager import broadcast_event
    broadcast_event("quotation_updated", out_quote.model_dump())
    
    return out_quote


@router.post("/{quote_id}/duplicate", response_model=schemas.QuotationOut)
def duplicate_quotation(quote_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to access this quotation")

    # Concurrency-safe retry loop for duplication quote number generation
    retries = 5
    new_q = None
    while retries > 0:
        next_number = get_calculated_next_number(db)
        existing = db.query(models.Quotation).filter(models.Quotation.quote_number == next_number).first()
        if existing:
            retries -= 1
            time.sleep(0.1)
            continue
            
        try:
            new_q = models.Quotation(
                id=str(uuid.uuid4()),
                quote_number=next_number,
                date=datetime.datetime.now().strftime("%d-%b-%Y"),
                customer_id=q.customer_id,
                customer_name=q.customer_name,
                customer_phone=q.customer_phone,
                customer_email=q.customer_email,
                customer_city=q.customer_city,
                customer_address=q.customer_address,
                customer_gstin=q.customer_gstin,
                items_json=q.items_json,
                gst_mode=q.gst_mode,
                subtotal=q.subtotal,
                delivery=q.delivery,
                discount_percent=q.discount_percent,
                discount_amount=q.discount_amount,
                gst_rate=q.gst_rate,
                gst_amount=q.gst_amount,
                cgst=q.cgst,
                sgst=q.sgst,
                igst=q.igst,
                grand_total=q.grand_total,
                terms_json=q.terms_json,
                validity_days=q.validity_days,
                payment_type=q.payment_type,
                status="Draft",
                payment_status="Pending",
                gst_type=q.gst_type or "exclusive",
                gst_inclusive=q.gst_inclusive or False,
                created_at=int(time.time() * 1000)
            )
            db.add(new_q)
            db.commit()
            db.refresh(new_q)
            break
        except Exception as e:
            db.rollback()
            retries -= 1
            if retries == 0:
                raise HTTPException(status_code=500, detail=f"Duplication failed due to database collision: {e}")
            time.sleep(0.1)
            
    if new_q and new_q.customer_phone:
        lead = db.query(models.Lead).filter(models.Lead.phone == new_q.customer_phone).first()
        if lead:
            from models import log_lead_activity
            log_lead_activity(db, lead.id, lead.lead_number, current_user.username or "System", current_user.role, "Quotation Duplicated", "", f"New Quote No: {new_q.quote_number}")
            db.commit()

    out_quote = _db_to_out(new_q)
    from websocket_manager import broadcast_event
    broadcast_event("quotation_created", out_quote.model_dump())
    return out_quote


@router.post("/{quote_id}/approve", response_model=schemas.QuotationOut)
def approve_quotation(quote_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to approve this quotation")
            
    q.status = "Approved"
    db.commit()
    db.refresh(q)
    
    # Log lead activity
    if q.customer_phone:
        lead = db.query(models.Lead).filter(models.Lead.phone == q.customer_phone).first()
        if lead:
            from models import log_lead_activity
            log_lead_activity(db, lead.id, lead.lead_number, current_user.username or "System", current_user.role, "Quotation Approved", "", f"Quote No: {q.quote_number}")
            db.commit()
            
    out_quote = _db_to_out(q)
    from websocket_manager import broadcast_event
    broadcast_event("quotation_updated", out_quote.model_dump())
    return out_quote


@router.post("/{quote_id}/convert", response_model=schemas.QuotationOut)
def convert_quotation(quote_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to convert this quotation")
            
    if q.status not in ["Approved", "Draft"]:
        raise HTTPException(status_code=400, detail="Only Draft or Approved quotations can be converted to Invoice")
        
    q.status = "Invoiced"
    db.commit()
    db.refresh(q)
    
    # Log lead activity
    if q.customer_phone:
        lead = db.query(models.Lead).filter(models.Lead.phone == q.customer_phone).first()
        if lead:
            from models import log_lead_activity
            log_lead_activity(db, lead.id, lead.lead_number, current_user.username or "System", current_user.role, "Quotation Converted to Invoice", "", f"Invoice No: {q.quote_number}")
            db.commit()
            
    out_quote = _db_to_out(q)
    from websocket_manager import broadcast_event
    broadcast_event("quotation_updated", out_quote.model_dump())
    return out_quote
