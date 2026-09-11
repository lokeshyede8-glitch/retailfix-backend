import uuid
import time
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from auth_utils import get_current_user, RoleChecker, CurrentUser

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("", response_model=schemas.PaymentOut, status_code=201)
def create_payment(payload: schemas.PaymentCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    # Verify quotation exists
    q = db.query(models.Quotation).filter(models.Quotation.id == payload.quotation_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
        
    if q.status in ["Draft", "Cancelled"]:
        raise HTTPException(status_code=400, detail="Payment cannot be recorded for this quotation.")
        
    if role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="You do not have permission to add payment for this quotation")
    
    if not q.customer_id:
        raise HTTPException(status_code=400, detail="Payment cannot be recorded because this quotation has no customer.")
        
    # Verify customer exists
    c = db.query(models.Customer).filter(models.Customer.id == payload.customer_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
        
    if q.customer_id != payload.customer_id:
        raise HTTPException(status_code=400, detail="Customer mismatch between quotation and payment")
        
    payment = models.Payment(
        id=str(uuid.uuid4()),
        quotation_id=payload.quotation_id,
        customer_id=payload.customer_id,
        invoice_number=payload.invoice_number,
        payment_type=payload.payment_type,
        amount=payload.amount,
        payment_date=payload.payment_date if payload.payment_date else int(time.time() * 1000),
        payment_mode=payload.payment_mode,
        transaction_id=payload.transaction_id or "",
        remarks=payload.remarks or "",
        created_by=payload.created_by or "Admin"
    )
    
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # Look for matching lead by customer phone to link payment event
    if q.customer_phone:
        lead = db.query(models.Lead).filter(models.Lead.phone == q.customer_phone).first()
        if lead:
            from models import log_lead_activity
            log_lead_activity(db, lead.id, lead.lead_number, payment.created_by or "System", "Admin" if (payment.created_by or "Admin") == "Admin" else "Salesman", "Payment Received", "", f"Amt: {payment.amount}, Mode: {payment.payment_mode}")
    
    # Now update quotation status and payment status
    all_payments = db.query(models.Payment).filter(models.Payment.quotation_id == q.id).all()
    total_paid = sum(p.amount for p in all_payments)
    
    if q.payment_type == "full_payment":
        # 100% Advance Payment flow
        # In this flow, payment sets status directly to Completed and payment_status to Paid
        q.status = "Completed"
        q.payment_status = "Paid"
    else:
        # 50% Advance + 50% Before Delivery flow
        if payload.payment_type == "Advance":
            q.status = "Advance Paid"
            q.payment_status = "Advance Paid"
        elif payload.payment_type == "Final":
            q.status = "Completed"
            q.payment_status = "Paid"
        else:
            # Fallback checks based on amount
            if total_paid >= q.grand_total:
                q.status = "Completed"
                q.payment_status = "Paid"
            elif total_paid > 0:
                q.status = "Advance Paid"
                q.payment_status = "Partial Paid"

    db.commit()
    db.refresh(q)
    
    # ── AUTO-GENERATE PRODUCTION ORDER FOR FACTORY DASHBOARD ────────────────────
    try:
        from routers.factory import generate_production_order_from_quotation
        po, is_new = generate_production_order_from_quotation(db, q.id)
        db.commit()
        if is_new and po:
            from websocket_manager import broadcast_event
            broadcast_event("new_production_order", {
                "id": po.id,
                "production_number": po.production_number,
                "quote_number": po.quote_number,
                "customer_name": po.customer_name,
                "status": po.status,
                "current_stage": po.current_stage
            })
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Auto generation of production order failed: {str(e)}")
        # We don't rollback the payment here, but we log safely.

    pay_data = {
        "id": payment.id,
        "quotation_id": payment.quotation_id,
        "customer_id": payment.customer_id,
        "invoice_number": payment.invoice_number,
        "payment_type": payment.payment_type,
        "amount": payment.amount,
        "payment_date": payment.payment_date,
        "payment_mode": payment.payment_mode,
        "transaction_id": payment.transaction_id,
        "remarks": payment.remarks,
        "created_by": payment.created_by
    }
    from websocket_manager import broadcast_event
    broadcast_event("payment_added", pay_data)
    broadcast_event("receipt_created", pay_data)
    
    return payment


@router.get("", response_model=List[schemas.PaymentOut])
def list_payments(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    if role_lower == "salesman":
        return (
            db.query(models.Payment)
            .join(models.Customer, models.Payment.customer_id == models.Customer.id)
            .join(models.Lead, models.Customer.phone == models.Lead.phone)
            .filter(
                models.Lead.salesman_id == current_user.id,
                models.Customer.phone != ""
            )
            .distinct()
            .order_by(models.Payment.payment_date.desc())
            .all()
        )
    return db.query(models.Payment).order_by(models.Payment.payment_date.desc()).all()


@router.get("/quotation/{quote_id}", response_model=List[schemas.PaymentOut])
def get_payments_by_quotation(quote_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if q and role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == q.customer_phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="Forbidden")
    return db.query(models.Payment).filter(models.Payment.quotation_id == quote_id).order_by(models.Payment.payment_date.asc()).all()


@router.get("/customer/{customer_id}", response_model=List[schemas.PaymentOut])
def get_payments_by_customer(customer_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if customer and role_lower == "salesman":
        lead = db.query(models.Lead).filter(
            models.Lead.salesman_id == current_user.id,
            models.Lead.phone == customer.phone
        ).first()
        if not lead:
            raise HTTPException(status_code=403, detail="Forbidden")
    return db.query(models.Payment).filter(models.Payment.customer_id == customer_id).order_by(models.Payment.payment_date.desc()).all()


@router.delete("/{payment_id}", status_code=204)
def delete_payment(payment_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
        
    pay_id = payment.id
    quote_id = payment.quotation_id
    db.delete(payment)
    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("payment_deleted", {"id": pay_id})
    
    # Recalculate quotation status on delete
    q = db.query(models.Quotation).filter(models.Quotation.id == quote_id).first()
    if q:
        all_payments = db.query(models.Payment).filter(models.Payment.quotation_id == q.id).all()
        total_paid = sum(p.amount for p in all_payments)
        if len(all_payments) == 0:
            if q.status in ["Completed", "Advance Paid"]:
                q.status = "Approved"
            q.payment_status = "Pending"
        else:
            if total_paid >= q.grand_total:
                q.status = "Completed"
                q.payment_status = "Paid"
            elif any(p.payment_type == "Advance" for p in all_payments):
                q.status = "Advance Paid"
                q.payment_status = "Advance Paid"
            else:
                q.status = "Approved"
                q.payment_status = "Partial Paid"
        db.commit()
        
        # Broadcast quotation updated
        from routers.quotations import _db_to_out
        out_quote = _db_to_out(q)
        broadcast_event("quotation_updated", out_quote.model_dump())
