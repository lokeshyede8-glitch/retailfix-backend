import uuid
import time
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, load_only
from sqlalchemy import or_, and_

from database import get_db
import models
import schemas
from auth_utils import get_current_user, CurrentUser

def check_followup_permission(lead, current_user: CurrentUser):
    role_lower = current_user.role.lower()
    if role_lower == "admin":
        return
    if role_lower == "salesman":
        if lead.salesman_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif role_lower == "telecaller":
        if not (
            lead.assigned_to == current_user.username or
            lead.current_owner == current_user.username or
            lead.created_by == current_user.username or
            lead.lead_source == "Salesman" or
            (lead.salesman_id and lead.salesman_id != "")
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/followups", tags=["followups"])


# Columns we need from the joined Lead row — photo is excluded intentionally.
_LEAD_COLUMNS = [
    models.Lead.id,
    models.Lead.customer_name,
    models.Lead.phone,
    models.Lead.shop_name,
    models.Lead.business_type,
    models.Lead.city,
    models.Lead.lead_number,
    models.Lead.lead_source,
    models.Lead.salesman_name,
    models.Lead.salesman_id,
    models.Lead.status,
    models.Lead.remarks,
]


@router.get("", response_model=list[schemas.FollowupOut])
def list_followups(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    t0 = time.perf_counter()
    user_role = current_user.role
    username = current_user.username

    # ── Use load_only on Lead so the photo TEXT blob is never loaded ─────────
    query = db.query(models.LeadFollowup, models.Lead).join(
        models.Lead, models.LeadFollowup.lead_id == models.Lead.id
    ).options(
        load_only(
            models.Lead.id,
            models.Lead.customer_name,
            models.Lead.phone,
            models.Lead.shop_name,
            models.Lead.business_type,
            models.Lead.city,
            models.Lead.lead_number,
            models.Lead.lead_source,
            models.Lead.salesman_name,
            models.Lead.salesman_id,
            models.Lead.status,
            models.Lead.remarks,
        )
    )

    role_lower = user_role.lower()
    if role_lower == 'salesman':
        query = query.filter(models.Lead.salesman_id == current_user.id)
    elif role_lower == 'telecaller':
        query = query.filter(
            (models.LeadFollowup.assigned_to == current_user.username) |
            (models.Lead.assigned_to == current_user.username) |
            (models.Lead.current_owner == current_user.username) |
            (models.Lead.created_by == current_user.username) |
            (models.Lead.lead_source == "Salesman") |
            (models.Lead.salesman_id != "")
        )

    results = query.all()
    t_query = time.perf_counter()

    out = []
    for f, l in results:
        # Get last remark from lead.remarks JSON list
        last_remark = ""
        try:
            parsed = json.loads(l.remarks)
            if isinstance(parsed, list) and len(parsed) > 0:
                last_remark = parsed[-1].get("note") or parsed[-1].get("message") or ""
        except Exception:
            last_remark = l.remarks or ""

        out.append(schemas.FollowupOut(
            id=f.id,
            lead_id=f.lead_id,
            priority=f.priority,
            follow_up_date=f.follow_up_date,
            follow_up_time=f.follow_up_time,
            status=f.status,
            notes=last_remark or f.notes,
            created_by_id=f.created_by_id or "",
            created_by_name=f.created_by_name or "",
            created_by=f.created_by or "",
            created_role=f.created_role or "",
            assigned_to=f.assigned_to or "",
            completed_date=f.completed_date or "",
            completed_at=f.completed_at,
            completed_by=f.completed_by,
            created_at=f.created_at,
            updated_at=f.updated_at,
            customer_name=l.customer_name,
            phone=l.phone,
            shop_name=l.shop_name,
            business_type=l.business_type,
            city=l.city,
            lead_number=l.lead_number,
            lead_source=l.lead_source,
            salesman_name=l.salesman_name,
            lead_status=l.status
        ))

    t_serial = time.perf_counter()
    logger.info(
        "GET /followups  role=%s  rows=%d  db=%.0fms  serialize=%.0fms  total=%.0fms",
        user_role, len(out),
        (t_query - t0) * 1000,
        (t_serial - t_query) * 1000,
        (t_serial - t0) * 1000,
    )
    return out


@router.post("", response_model=schemas.FollowupOut)
def create_followup(
    payload: schemas.FollowupCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    user_role = current_user.role.title()
    username = current_user.username
    lead = db.query(models.Lead).filter(models.Lead.id == payload.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    check_followup_permission(lead, current_user)

    # Enforce exactly one follow-up record per lead
    existing = db.query(models.LeadFollowup).filter(
        models.LeadFollowup.lead_id == payload.lead_id
    ).first()

    now = int(time.time() * 1000)
    if existing:
        old_date = existing.follow_up_date
        old_time = existing.follow_up_time
        old_status = existing.status

        existing.priority = payload.priority
        existing.follow_up_date = payload.follow_up_date
        existing.follow_up_time = payload.follow_up_time or "12:00 PM"
        existing.notes = payload.notes or ""
        existing.status = "Pending"
        existing.updated_at = now

        lead.follow_up_date = payload.follow_up_date

        if current_user.role.lower() == "telecaller":
            from models import log_telecaller_activity
            log_telecaller_activity(
                db,
                lead_id=payload.lead_id,
                telecaller_name=username,
                action_type="Followup Rescheduled",
                old_value=f"{old_date} {old_time}",
                new_value=f"{payload.follow_up_date} {payload.follow_up_time or '12:00 PM'}",
                remark=f"Follow-up rescheduled from {old_date} {old_time} to {payload.follow_up_date} {payload.follow_up_time or '12:00 PM'}.",
                request=request
            )

        # Log history of this reschedule
        date_str = time.strftime("%d-%b-%Y")
        time_str = time.strftime("%I:%M %p")
        h = models.FollowupHistory(
            id=str(uuid.uuid4()),
            followup_id=existing.id,
            lead_id=payload.lead_id,
            old_date=old_date,
            new_date=payload.follow_up_date,
            old_time=old_time,
            new_time=payload.follow_up_time or "12:00 PM",
            old_status=old_status,
            new_status="Pending",
            user=payload.created_by_name or username,
            role=payload.created_role or user_role,
            timestamp=now,
            changed_by=payload.created_by_name or username,
            changed_at=now,
            date=date_str,
            time=time_str
        )
        db.add(h)

        # Notify assigned user, salesman, and admin about reschedule
        from models import create_notification
        msg = f"Follow-up rescheduled for {lead.customer_name} to {payload.follow_up_date} {payload.follow_up_time or '12:00 PM'} by {username} ({user_role})."
        if existing.assigned_to:
            create_notification(db, message=msg, type="New Followup", user_id=existing.assigned_to, lead_id=lead.id)
        if lead.salesman_name and lead.salesman_name != existing.assigned_to:
            create_notification(db, message=msg, type="New Followup", user_id=lead.salesman_name, lead_id=lead.id)
        create_notification(db, message=msg, type="New Followup", role="admin", lead_id=lead.id)

        db.commit()
        db.refresh(existing)
        f = existing
    else:
        f = models.LeadFollowup(
            id=str(uuid.uuid4()),
            lead_id=payload.lead_id,
            priority=payload.priority,
            follow_up_date=payload.follow_up_date,
            follow_up_time=payload.follow_up_time or "12:00 PM",
            status="Pending",
            notes=payload.notes or "",
            created_by_id=payload.created_by_id or "",
            created_by_name=payload.created_by_name or username,
            created_by=payload.created_by_name or username,
            created_role=payload.created_role or user_role,
            assigned_to=lead.assigned_to or "",
            completed_date="",
            created_at=now,
            updated_at=now
        )
        db.add(f)
        lead.follow_up_date = payload.follow_up_date
        if current_user.role.lower() == "telecaller":
            from models import log_telecaller_activity
            log_telecaller_activity(
                db,
                lead_id=payload.lead_id,
                telecaller_name=username,
                action_type="Followup Created",
                old_value="",
                new_value=f"{payload.follow_up_date} {payload.follow_up_time or '12:00 PM'}",
                remark=f"Follow-up scheduled for {payload.follow_up_date} {payload.follow_up_time or '12:00 PM'}.",
                request=request
            )

        # Notify assigned user, salesman, and admin about new followup
        from models import create_notification
        msg = f"New Follow-up scheduled for {lead.customer_name} on {payload.follow_up_date} {payload.follow_up_time or '12:00 PM'} by {username} ({user_role})."
        if f.assigned_to:
            create_notification(db, message=msg, type="New Followup", user_id=f.assigned_to, lead_id=lead.id)
        if lead.salesman_name and lead.salesman_name != f.assigned_to:
            create_notification(db, message=msg, type="New Followup", user_id=lead.salesman_name, lead_id=lead.id)
        create_notification(db, message=msg, type="New Followup", role="admin", lead_id=lead.id)

        db.commit()
        db.refresh(f)
    from websocket_manager import broadcast_event
    broadcast_event("followup_changed", {
        "id": f.id,
        "lead_id": f.lead_id,
        "salesman_id": lead.salesman_id if lead else "",
        "assigned_to": f.assigned_to or (lead.assigned_to if lead else ""),
        "follow_up_date": f.follow_up_date,
        "follow_up_time": f.follow_up_time,
        "status": f.status,
        "priority": f.priority
    })

    return schemas.FollowupOut(
        id=f.id,
        lead_id=f.lead_id,
        priority=f.priority,
        follow_up_date=f.follow_up_date,
        follow_up_time=f.follow_up_time,
        status=f.status,
        notes=f.notes,
        created_by_id=f.created_by_id or "",
        created_by_name=f.created_by_name or "",
        created_by=f.created_by or "",
        created_role=f.created_role or "",
        assigned_to=f.assigned_to or "",
        completed_date=f.completed_date or "",
        completed_at=f.completed_at,
        completed_by=f.completed_by,
        created_at=f.created_at,
        updated_at=f.updated_at,
        customer_name=lead.customer_name,
        phone=lead.phone,
        shop_name=lead.shop_name,
        business_type=lead.business_type,
        city=lead.city,
        lead_number=lead.lead_number,
        lead_source=lead.lead_source,
        salesman_name=lead.salesman_name,
        lead_status=lead.status
    )


@router.put("/{followup_id}", response_model=schemas.FollowupOut)
def update_followup(
    followup_id: str,
    payload: schemas.FollowupUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    user_role = current_user.role.title()
    username = current_user.username
    role_check = payload.edited_by_role or user_role
    f = db.query(models.LeadFollowup).filter(models.LeadFollowup.id == followup_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Follow-up not found")

    lead = db.query(models.Lead).filter(models.Lead.id == f.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    check_followup_permission(lead, current_user)

    now = int(time.time() * 1000)
    old_date = f.follow_up_date
    old_time = f.follow_up_time
    old_status = f.status

    modified = False
    history_log = False

    if payload.priority is not None:
        f.priority = payload.priority
        modified = True

    if payload.notes is not None:
        f.notes = payload.notes
        modified = True

    if payload.follow_up_date is not None and payload.follow_up_date != f.follow_up_date:
        f.follow_up_date = payload.follow_up_date
        lead.follow_up_date = payload.follow_up_date
        modified = True
        history_log = True

    if payload.follow_up_time is not None and payload.follow_up_time != f.follow_up_time:
        f.follow_up_time = payload.follow_up_time
        modified = True
        history_log = True

    if payload.status is not None and payload.status != f.status:
        f.status = payload.status
        modified = True
        history_log = True
        if payload.status == "Completed":
            f.completed_at = now
            f.completed_by = payload.completed_by or payload.edited_by_name or "System"
            f.completed_date = payload.completed_date or time.strftime("%Y-%m-%d")
            models.log_lead_activity(
                db, lead.id, lead.lead_number,
                f.completed_by, role_check,
                "Follow-up Completed", "", ""
            )
            if role_check.lower() == "telecaller":
                from models import log_telecaller_activity
                log_telecaller_activity(
                    db,
                    lead_id=lead.id,
                    telecaller_name=f.completed_by,
                    action_type="Followup Completed",
                    old_value=old_status,
                    new_value="Completed",
                    remark="Follow-up marked as Completed.",
                    request=request
                )
            elif role_check.lower() == "salesman":
                from models import log_salesman_activity
                log_salesman_activity(
                    db,
                    lead_id=lead.id,
                    salesman_name=f.completed_by,
                    activity_type="Visit Completed" if f.notes and "visit" in f.notes.lower() else "Follow-up Completed",
                    old_value=old_status,
                    new_value="Completed",
                    remark="Follow-up marked as Completed.",
                    request=request
                )

            # Notify creator, salesman, and admin about completion
            from models import create_notification
            msg = f"Follow-up completed for {lead.customer_name} by {f.completed_by}."
            if f.created_by_name:
                create_notification(db, message=msg, type="Followup Completed", user_id=f.created_by_name, lead_id=lead.id)
            if lead.salesman_name and lead.salesman_name != f.created_by_name:
                create_notification(db, message=msg, type="Followup Completed", user_id=lead.salesman_name, lead_id=lead.id)
            create_notification(db, message=msg, type="Followup Completed", role="admin", lead_id=lead.id)
        elif payload.status == "Pending":
            f.completed_at = 0
            f.completed_by = ""
            f.completed_date = ""

    if modified:
        f.updated_at = now

    if history_log:
        date_str = time.strftime("%d-%b-%Y")
        time_str = time.strftime("%I:%M %p")
        h = models.FollowupHistory(
            id=str(uuid.uuid4()),
            followup_id=f.id,
            lead_id=f.lead_id,
            old_date=old_date,
            new_date=f.follow_up_date,
            old_time=old_time,
            new_time=f.follow_up_time,
            old_status=old_status,
            new_status=f.status,
            user=payload.edited_by_name or "System",
            role=role_check,
            timestamp=now,
            changed_by=payload.edited_by_name or "System",
            changed_at=now,
            date=date_str,
            time=time_str
        )
        db.add(h)

        models.log_lead_activity(
            db, lead.id, lead.lead_number,
            payload.edited_by_name or "System", role_check,
            "Follow-up Rescheduled",
            f"{old_date} {old_time} ({old_status})",
            f"{f.follow_up_date} {f.follow_up_time} ({f.status})"
        )

        if role_check.lower() == "telecaller" and (payload.follow_up_date is not None or payload.follow_up_time is not None):
            from models import log_telecaller_activity
            log_telecaller_activity(
                db,
                lead_id=lead.id,
                telecaller_name=payload.edited_by_name or "System",
                action_type="Followup Rescheduled",
                old_value=f"{old_date} {old_time}",
                new_value=f"{f.follow_up_date} {f.follow_up_time}",
                remark=f"Follow-up rescheduled from {old_date} {old_time} to {f.follow_up_date} {f.follow_up_time}.",
                request=request
            )

        # Notify assigned user, salesman, and admin about reschedule
        from models import create_notification
        msg = f"Follow-up rescheduled for {lead.customer_name} to {f.follow_up_date} {f.follow_up_time} by {payload.edited_by_name or 'System'}."
        if f.assigned_to:
            create_notification(db, message=msg, type="New Followup", user_id=f.assigned_to, lead_id=lead.id)
        if lead.salesman_name and lead.salesman_name != f.assigned_to:
            create_notification(db, message=msg, type="New Followup", user_id=lead.salesman_name, lead_id=lead.id)
        create_notification(db, message=msg, type="New Followup", role="admin", lead_id=lead.id)

    # One single commit covers all mutations in this request
    if modified or history_log:
        db.commit()
        db.refresh(f)

    from websocket_manager import broadcast_event
    broadcast_event("followup_changed", {
        "id": f.id,
        "lead_id": f.lead_id,
        "salesman_id": lead.salesman_id if lead else "",
        "assigned_to": f.assigned_to or (lead.assigned_to if lead else ""),
        "follow_up_date": f.follow_up_date,
        "follow_up_time": f.follow_up_time,
        "status": f.status,
        "priority": f.priority
    })

    return schemas.FollowupOut(
        id=f.id,
        lead_id=f.lead_id,
        priority=f.priority,
        follow_up_date=f.follow_up_date,
        follow_up_time=f.follow_up_time,
        status=f.status,
        notes=f.notes,
        created_by_id=f.created_by_id or "",
        created_by_name=f.created_by_name or "",
        created_by=f.created_by or "",
        created_role=f.created_role or "",
        assigned_to=f.assigned_to or "",
        completed_date=f.completed_date or "",
        completed_at=f.completed_at,
        completed_by=f.completed_by,
        created_at=f.created_at,
        updated_at=f.updated_at,
        customer_name=lead.customer_name,
        phone=lead.phone,
        shop_name=lead.shop_name,
        business_type=lead.business_type,
        city=lead.city,
        lead_number=lead.lead_number,
        lead_source=lead.lead_source,
        salesman_name=lead.salesman_name,
        lead_status=lead.status
    )


@router.get("/{followup_id}/history", response_model=list[schemas.FollowupHistoryOut])
def get_followup_history(followup_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    f = db.query(models.LeadFollowup).filter(models.LeadFollowup.id == followup_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    lead = db.query(models.Lead).filter(models.Lead.id == f.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_followup_permission(lead, current_user)
    return db.query(models.FollowupHistory).filter(
        models.FollowupHistory.followup_id == followup_id
    ).order_by(models.FollowupHistory.timestamp.desc()).all()


@router.delete("/{followup_id}")
def delete_followup(
    followup_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    if current_user.role.lower() != 'admin':
        raise HTTPException(status_code=403, detail="Only Admin can delete follow-ups")

    f = db.query(models.LeadFollowup).filter(models.LeadFollowup.id == followup_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Follow-up not found")

    lead_id_to_delete = f.lead_id
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id_to_delete).first()
    f_id = f.id
    f_assigned_to = f.assigned_to or (lead.assigned_to if lead else "")
    f_salesman_id = lead.salesman_id if lead else ""

    db.delete(f)
    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("followup_changed", {
        "id": f_id,
        "lead_id": lead_id_to_delete,
        "salesman_id": f_salesman_id,
        "assigned_to": f_assigned_to,
        "status": "Deleted"
    })
    
    return {"status": "deleted"}
