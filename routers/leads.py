import uuid
import time
import logging
import os
import json
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.orm import Session, load_only
from sqlalchemy import func

from database import get_db
import models
import schemas
from auth_utils import get_current_user, RoleChecker, CurrentUser, normalize_phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])


def check_lead_permission(lead, current_user: CurrentUser):
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



def sync_lead_followup(db: Session, lead, new_date: str, changer_name: str, changer_role: str = "System", changer_id: str = ""):
    if not new_date:
        active = db.query(models.LeadFollowup).filter(
            models.LeadFollowup.lead_id == lead.id,
            models.LeadFollowup.status == "Pending"
        ).first()
        if active:
            active.status = "Completed"
            active.completed_at = int(time.time() * 1000)
            active.completed_by = changer_name
            active.completed_date = time.strftime("%Y-%m-%d")
            db.flush()

            # Log completion to history
            now = int(time.time() * 1000)
            date_str = time.strftime("%d-%b-%Y")
            time_str = time.strftime("%I:%M %p")
            h = models.FollowupHistory(
                id=str(uuid.uuid4()),
                followup_id=active.id,
                lead_id=lead.id,
                old_date=active.follow_up_date,
                new_date=active.follow_up_date,
                old_time=active.follow_up_time,
                new_time=active.follow_up_time,
                old_status="Pending",
                new_status="Completed",
                user=changer_name,
                role=changer_role,
                timestamp=now,
                changed_by=changer_name,
                changed_at=now,
                date=date_str,
                time=time_str
            )
            db.add(h)
            db.flush()
        return

    now = int(time.time() * 1000)
    active = db.query(models.LeadFollowup).filter(
        models.LeadFollowup.lead_id == lead.id,
        models.LeadFollowup.status == "Pending"
    ).first()

    if active:
        old_date = active.follow_up_date
        old_time = active.follow_up_time
        if old_date != new_date:
            active.follow_up_date = new_date
            active.updated_at = now
            db.flush()

            date_str = time.strftime("%d-%b-%Y")
            time_str = time.strftime("%I:%M %p")
            h = models.FollowupHistory(
                id=str(uuid.uuid4()),
                followup_id=active.id,
                lead_id=lead.id,
                old_date=old_date,
                new_date=new_date,
                old_time=old_time,
                new_time=active.follow_up_time,
                old_status="Pending",
                new_status="Pending",
                user=changer_name,
                role=changer_role,
                timestamp=now,
                changed_by=changer_name,
                changed_at=now,
                date=date_str,
                time=time_str
            )
            db.add(h)
            db.flush()
    else:
        clean_notes = ""
        if lead.remarks:
            try:
                parsed = json.loads(lead.remarks)
                if isinstance(parsed, list) and len(parsed) > 0:
                    last = parsed[-1]
                    clean_notes = last.get("note") or last.get("message") or ""
                else:
                    clean_notes = lead.remarks
            except Exception:
                clean_notes = lead.remarks

        new_f = models.LeadFollowup(
            id=str(uuid.uuid4()),
            lead_id=lead.id,
            priority="Medium",
            follow_up_date=new_date,
            follow_up_time="12:00 PM",
            status="Pending",
            notes=clean_notes,
            created_by_id=changer_id,
            created_by_name=changer_name,
            created_by=changer_name,
            created_role=changer_role,
            assigned_to=lead.assigned_to or "",
            created_at=now,
            updated_at=now
        )
        db.add(new_f)
        db.flush()


def _next_lead_number(db: Session) -> str:
    max_lead = db.query(models.Lead.lead_number).filter(models.Lead.lead_number.like("LD-%")).order_by(models.Lead.lead_number.desc()).first()
    if max_lead:
        try:
            num = int(max_lead[0].split("-")[1])
            return f"LD-{num + 1:04d}"
        except (ValueError, IndexError):
            pass
    count = db.query(func.count(models.Lead.id)).scalar()
    return f"LD-{count + 1:04d}"


def _build_lead_dict(lead, has_photo: bool) -> dict:
    """Convert a Lead ORM object to a plain dict for the response."""
    if lead.updated_at is None:
        lead.updated_at = lead.created_at
    return {
        "id": lead.id,
        "lead_number": lead.lead_number,
        "salesman_id": lead.salesman_id,
        "salesman_name": lead.salesman_name,
        "customer_name": lead.customer_name,
        "phone": lead.phone,
        "shop_name": lead.shop_name,
        "address": lead.address,
        "city": lead.city,
        "pincode": lead.pincode,
        "business_type": lead.business_type,
        "remarks": lead.remarks,
        "follow_up_date": lead.follow_up_date,
        "latitude": lead.latitude,
        "longitude": lead.longitude,
        "photo": "HAS_PHOTO" if has_photo else "",
        "status": lead.status,
        "lead_source": getattr(lead, "lead_source", ""),
        "facebook_lead_id": getattr(lead, "facebook_lead_id", ""),
        "campaign_id": getattr(lead, "campaign_id", ""),
        "campaign_name": getattr(lead, "campaign_name", ""),
        "adset_id": getattr(lead, "adset_id", ""),
        "adset_name": getattr(lead, "adset_name", ""),
        "ad_id": getattr(lead, "ad_id", ""),
        "ad_name": getattr(lead, "ad_name", ""),
        "page_id": getattr(lead, "page_id", ""),
        "form_id": getattr(lead, "form_id", ""),
        "platform": getattr(lead, "platform", ""),
        "assigned_to": getattr(lead, "assigned_to", ""),
        "meta_created_time": getattr(lead, "meta_created_time", ""),
        "sync_status": getattr(lead, "sync_status", ""),
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "created_by": getattr(lead, "created_by", "") or "",
        "current_owner": getattr(lead, "current_owner", "") or "",
        "last_updated_by": getattr(lead, "last_updated_by", "") or "",
        "store_images_json": getattr(lead, "store_images_json", "[]") or "[]",
        "store_videos_json": getattr(lead, "store_videos_json", "[]") or "[]",
    }


# Columns fetched for list views — excludes the heavy base64 photo blob.
_LIST_COLUMNS = [
    models.Lead.id, models.Lead.lead_number, models.Lead.salesman_id,
    models.Lead.salesman_name, models.Lead.customer_name, models.Lead.phone,
    models.Lead.shop_name, models.Lead.address, models.Lead.city,
    models.Lead.pincode, models.Lead.business_type, models.Lead.remarks,
    models.Lead.follow_up_date, models.Lead.latitude, models.Lead.longitude,
    models.Lead.status, models.Lead.lead_source, models.Lead.facebook_lead_id,
    models.Lead.campaign_id, models.Lead.campaign_name, models.Lead.adset_id,
    models.Lead.adset_name, models.Lead.ad_id, models.Lead.ad_name,
    models.Lead.page_id, models.Lead.form_id, models.Lead.platform,
    models.Lead.assigned_to, models.Lead.meta_created_time,
    models.Lead.sync_status, models.Lead.created_at, models.Lead.updated_at,
    models.Lead.created_by, models.Lead.current_owner,
    models.Lead.last_updated_by,
    models.Lead.store_images_json,
    models.Lead.store_videos_json,
    # Lightweight existence check — func.length returns an int, not the blob.
    func.length(models.Lead.photo).label("photo_len"),
]


@router.get("", response_model=list[schemas.LeadOut])
def list_leads(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    t0 = time.perf_counter()

    query = db.query(*_LIST_COLUMNS)
    role_lower = current_user.role.lower()
    if role_lower == "salesman":
        query = query.filter(models.Lead.salesman_id == current_user.id)
    elif role_lower == "telecaller":
        query = query.filter(
            (models.Lead.assigned_to == current_user.username) |
            (models.Lead.current_owner == current_user.username) |
            (models.Lead.created_by == current_user.username) |
            (models.Lead.lead_source == "Salesman") |
            (models.Lead.salesman_id != "")
        )

    rows = query.order_by(models.Lead.created_at.desc()).all()

    t_query = time.perf_counter()
    result = [_build_lead_dict(row, bool(row.photo_len)) for row in rows]
    t_serial = time.perf_counter()

    logger.info(
        "GET /leads  rows=%d  db=%.0fms  serialize=%.0fms  total=%.0fms",
        len(rows),
        (t_query - t0) * 1000,
        (t_serial - t_query) * 1000,
        (t_serial - t0) * 1000,
    )
    return result


@router.get("/salesman/{salesman_id}", response_model=list[schemas.LeadOut])
def leads_by_salesman(salesman_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    t0 = time.perf_counter()
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
    if role_lower == "salesman" and current_user.id != salesman_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    rows = (
        db.query(*_LIST_COLUMNS)
        .filter(models.Lead.salesman_id == salesman_id)
        .order_by(models.Lead.created_at.desc())
        .all()
    )

    t_query = time.perf_counter()
    result = [_build_lead_dict(row, bool(row.photo_len)) for row in rows]
    t_serial = time.perf_counter()

    logger.info(
        "GET /leads/salesman/%s  rows=%d  db=%.0fms  serialize=%.0fms  total=%.0fms",
        salesman_id, len(rows),
        (t_query - t0) * 1000,
        (t_serial - t_query) * 1000,
        (t_serial - t0) * 1000,
    )
    return result


@router.get("/stats")
def lead_stats(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    t0 = time.perf_counter()

    # ── One query for all salesmen ──────────────────────────────────────────
    salesmen = db.query(models.Salesman).filter(models.Salesman.active == True).all()

    # ── One aggregated query for all lead counts — no per-salesman loop ─────
    from sqlalchemy import case
    lead_rows = (
        db.query(
            models.Lead.salesman_id,
            func.count(models.Lead.id).label("total"),
            func.sum(
                case((models.Lead.status == "Converted", 1), else_=0)
            ).label("converted"),
        )
        .group_by(models.Lead.salesman_id)
        .all()
    )
    # Build a dict keyed by salesman_id for O(1) lookup
    counts = {r.salesman_id: (r.total, r.converted or 0) for r in lead_rows}

    result = []
    for s in salesmen:
        total, converted = counts.get(s.id, (0, 0))
        result.append({
            "salesman_id": s.id,
            "salesman_name": s.name,
            "total_leads": total,
            "converted": converted,
            "conversion_rate": round(converted / total * 100, 1) if total > 0 else 0,
        })

    logger.info("GET /leads/stats  %.0fms", (time.perf_counter() - t0) * 1000)
    return result


@router.post("", response_model=schemas.LeadOut)
def create_lead(data: schemas.LeadCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    user = current_user.username
    role = current_user.role.title()
    
    salesman = None
    role_lower = current_user.role.lower()
    if role_lower == "salesman":
        salesman_id = current_user.id
        salesman = current_user.user
        data.salesman_id = current_user.id
        data.salesman_name = current_user.username
    else:
        salesman_id = data.salesman_id
        if salesman_id:
            salesman = db.query(models.Salesman).filter(models.Salesman.id == salesman_id).first()
            if not salesman:
                raise HTTPException(status_code=404, detail="Salesman not found")
    now = int(time.time() * 1000)

    resolved_source = data.lead_source or "Online"
    if role.lower() == "salesman":
        resolved_source = "Salesman"
    elif role.lower() == "telecaller":
        if resolved_source not in ["Online", "Website", "Meta", "Google Sheet"]:
            resolved_source = "Online"

    import time as _time
    import json

    # Capture the initial note timestamp
    now_dt = _time.localtime()
    note_date_str = _time.strftime("%d-%b-%Y", now_dt)  # 02-Jul-2026
    note_time_str = _time.strftime("%I:%M %p", now_dt)  # 11:30 AM
    
    initial_note = (data.created_note or "").strip()
    remarks_val = (data.remarks or "").strip()

    is_remarks_json = False
    if remarks_val.startswith("["):
        try:
            parsed = json.loads(remarks_val)
            if isinstance(parsed, list):
                is_remarks_json = True
        except Exception:
            pass

    if remarks_val and not is_remarks_json:
        # Remarks is a plain string. Let's make it the initial visit note and wrap it in a JSON array.
        if not initial_note:
            initial_note = remarks_val
        
        note_dict = {
            "date": note_date_str,
            "time": note_time_str,
            "salesman": salesman.name if salesman else user,
            "username": user,
            "role": role.lower(),
            "note": remarks_val,
            "message": remarks_val
        }
        remarks_val = json.dumps([note_dict])

    lead = models.Lead(
        id=str(uuid.uuid4()),
        lead_number=_next_lead_number(db),
        salesman_id=data.salesman_id or "",
        salesman_name=data.salesman_name or (salesman.name if salesman else ""),
        customer_name=data.customer_name,
        phone=normalize_phone(data.phone) if data.phone else "",
        shop_name=data.shop_name or "",
        address=data.address or "",
        city=data.city or "",
        pincode=data.pincode or "",
        business_type=data.business_type or "",
        remarks=remarks_val,
        follow_up_date=data.follow_up_date or "",
        latitude=data.latitude,
        longitude=data.longitude,
        photo=data.photo or "",
        status=data.status or "New Lead",
        lead_source=resolved_source,
        created_by=user,
        store_width=data.store_width,
        store_length=data.store_length,
        store_height=data.store_height,
        store_area=data.store_area,

        current_owner=data.salesman_name or (salesman.name if salesman else "System"),
        last_updated_by=user,
        store_images_json=data.store_images_json or "[]",
        store_videos_json=data.store_videos_json or "[]",
        # Permanent initial visit note fields
        created_note=initial_note,
        created_note_by=user,
        created_note_date=note_date_str,
        created_note_time=note_time_str,
        created_at=now,
        updated_at=now,
    )
    db.add(lead)
    db.flush()  # Assign id before referencing in follow-up / activity

    creator_id = data.created_by_id or data.salesman_id or (salesman.id if salesman else "")
    if lead.follow_up_date:
        sync_lead_followup(db, lead, lead.follow_up_date, user, role, creator_id)

    # Log lead created activity
    from models import log_lead_activity, log_salesman_activity, log_telecaller_activity
    log_lead_activity(db, lead.id, lead.lead_number, user, role, "Lead Created", "", "")

    # Log the initial visit note to the Salesman/Telecaller Activity timeline
    if initial_note:
        if role.lower() == "salesman":
            log_salesman_activity(
                db,
                lead_id=lead.id,
                salesman_name=user,
                activity_type="Visit Note",
                remark=initial_note,
            )
        elif role.lower() == "telecaller":
            log_telecaller_activity(
                db,
                lead_id=lead.id,
                telecaller_name=user,
                action_type="Remark",
                remark=initial_note,
            )

    # Log location if captured
    if lead.latitude is not None and lead.longitude is not None:
        log_lead_activity(db, lead.id, lead.lead_number, user, role, "Location Captured", "", f"Lat: {lead.latitude}, Lng: {lead.longitude}")
        if role.lower() == "salesman":
            log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Location Captured", latitude=lead.latitude, longitude=lead.longitude)

    # Log photo if uploaded initially
    if lead.photo:
        log_lead_activity(db, lead.id, lead.lead_number, user, role, "Photo Uploaded", "", lead.photo)

    # Log initial media if uploaded
    try:
        init_imgs = json.loads(lead.store_images_json or "[]")
        if init_imgs:
            log_lead_activity(db, lead.id, lead.lead_number, user, role, "Media Uploaded", "", f"Uploaded {len(init_imgs)} store image{'s' if len(init_imgs) > 1 else ''}.")
            if role.lower() == "salesman":
                log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Store Media Uploaded", remark=f"Uploaded {len(init_imgs)} store image{'s' if len(init_imgs) > 1 else ''}.")
    except Exception as e:
        logger.error(f"Error logging initial images: {e}")

    try:
        init_vids = json.loads(lead.store_videos_json or "[]")
        if init_vids:
            log_lead_activity(db, lead.id, lead.lead_number, user, role, "Media Uploaded", "", f"Uploaded {len(init_vids)} store video{'s' if len(init_vids) > 1 else ''}.")
            if role.lower() == "salesman":
                log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Store Media Uploaded", remark=f"Uploaded {len(init_vids)} store video{'s' if len(init_vids) > 1 else ''}.")
    except Exception as e:
        logger.error(f"Error logging initial videos: {e}")

    db.commit()
    db.refresh(lead)
    
    lead_data = {
        "id": lead.id,
        "lead_number": lead.lead_number,
        "salesman_id": lead.salesman_id,
        "salesman_name": lead.salesman_name,
        "customer_name": lead.customer_name,
        "phone": lead.phone,
        "shop_name": lead.shop_name,
        "address": lead.address,
        "city": lead.city,
        "pincode": lead.pincode,
        "business_type": lead.business_type,
        "remarks": lead.remarks,
        "follow_up_date": lead.follow_up_date,
        "latitude": lead.latitude,
        "longitude": lead.longitude,
        "photo": lead.photo,
        "status": lead.status,
        "lead_source": lead.lead_source,
        "assigned_to": lead.assigned_to,
        "created_by": lead.created_by,
        "current_owner": lead.current_owner,
        "last_updated_by": lead.last_updated_by,
        "created_note": lead.created_note,
        "created_note_by": lead.created_note_by,
        "created_note_date": lead.created_note_date,
        "created_note_time": lead.created_note_time,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "store_images_json": lead.store_images_json,
        "store_videos_json": lead.store_videos_json,
    }
    from websocket_manager import broadcast_event
    broadcast_event("lead_created", lead_data)
    
    if (lead.store_images_json and lead.store_images_json != "[]") or (lead.store_videos_json and lead.store_videos_json != "[]"):
        broadcast_event("lead_media_updated", {
            "lead_id": lead.id,
            "salesman_id": lead.salesman_id,
            "assigned_to": lead.assigned_to,
            "store_images_json": lead.store_images_json,
            "store_videos_json": lead.store_videos_json
        })
    
    return lead


@router.put("/{lead_id}", response_model=schemas.LeadOut)
def update_lead(lead_id: str, data: schemas.LeadUpdate, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    check_lead_permission(lead, current_user)

    # Get who performed this action
    user = current_user.username
    role = current_user.role.title()

    status_changed = False
    old_status = lead.status
    followup_changed = False
    remark_added = False
    remark_msg = ""

    from models import log_lead_activity, log_telecaller_activity, log_salesman_activity
    import json

    # Track fields for log_activity
    # 1. Status change
    if data.status is not None and data.status != lead.status:
        status_changed = True
        log_lead_activity(db, lead.id, lead.lead_number, user, role, "Status Changed", lead.status, data.status)
        if role.lower() == "telecaller":
            log_telecaller_activity(db, lead_id=lead.id, telecaller_name=user, action_type="Status Updated", old_value=lead.status, new_value=data.status, remark=f"Status changed from {lead.status} to {data.status}", request=request)
        elif role.lower() == "salesman":
            log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Status Changed", old_value=lead.status, new_value=data.status, remark=f"Status changed from {lead.status} to {data.status}", request=request)
        
        # Notify user, salesman, and admin about status change
        from models import create_notification
        msg = f"Lead {lead.customer_name} (#{lead.lead_number}) status changed to {data.status} by {user}."
        if lead.assigned_to:
            create_notification(db, message=msg, type="Status Changed", user_id=lead.assigned_to, lead_id=lead.id)
        if lead.salesman_name:
            create_notification(db, message=msg, type="Status Changed", user_id=lead.salesman_name, lead_id=lead.id)
        create_notification(db, message=msg, type="Status Changed", role="admin", lead_id=lead.id)

        lead.status = data.status
        lead.last_updated_by = user
        # Handle owners logic on status updates
        if data.status == "Converted":
            log_lead_activity(db, lead.id, lead.lead_number, user, role, "Lead Converted", "", "")
        elif data.status == "Lost":
            log_lead_activity(db, lead.id, lead.lead_number, user, role, "Lead Lost", "", "")

    # 2. Remarks change / Remark Edited
    if data.remarks is not None and data.remarks != lead.remarks:
        is_notes_json = False
        try:
            old_arr = json.loads(lead.remarks)
            new_arr = json.loads(data.remarks)
            if isinstance(old_arr, list) and isinstance(new_arr, list):
                is_notes_json = True
                if len(new_arr) > len(old_arr):
                    # Note Added! Get the last note text
                    last_note = new_arr[-1]
                    note_msg = last_note.get("note") or last_note.get("message") or ""
                    remark_added = True
                    remark_msg = note_msg
                    # Log the uploader details
                    log_lead_activity(db, lead.id, lead.lead_number, last_note.get("salesman") or last_note.get("username") or user, last_note.get("role") or role, "Note Added", "", note_msg)
                    if (last_note.get("role") or "").lower() == "telecaller" or role.lower() == "telecaller":
                        log_telecaller_activity(db, lead_id=lead.id, telecaller_name=last_note.get("salesman") or last_note.get("username") or user, action_type="Remark Added", remark=note_msg, request=request)
                    elif (last_note.get("role") or "").lower() == "salesman" or role.lower() == "salesman":
                        log_salesman_activity(db, lead_id=lead.id, salesman_name=last_note.get("salesman") or last_note.get("username") or user, activity_type="General Note", remark=note_msg, request=request)
                else:
                    log_lead_activity(db, lead.id, lead.lead_number, user, role, "Remark Edited", lead.remarks, data.remarks)
        except Exception:
            pass

        if not is_notes_json:
            log_lead_activity(db, lead.id, lead.lead_number, user, role, "Remark Edited", lead.remarks, data.remarks)

        lead.remarks = data.remarks
        lead.last_updated_by = user

    # 3. Follow-up Date change
    if data.follow_up_date is not None and data.follow_up_date != lead.follow_up_date:
        followup_changed = True
        sync_lead_followup(db, lead, data.follow_up_date, user, role, data.edited_by_id or "")
        if role.lower() == "telecaller":
            log_telecaller_activity(
                db,
                lead_id=lead.id,
                telecaller_name=user,
                action_type="Followup Rescheduled",
                old_value=lead.follow_up_date or "None",
                new_value=data.follow_up_date or "None",
                remark=f"Next Follow-up changed from {lead.follow_up_date or 'None'} to {data.follow_up_date or 'None'}",
                request=request
            )
        elif role.lower() == "salesman":
            log_salesman_activity(
                db,
                lead_id=lead.id,
                salesman_name=user,
                activity_type="Follow-up Date Changed",
                old_value=lead.follow_up_date or "None",
                new_value=data.follow_up_date or "None",
                remark=f"Next Follow-up changed from {lead.follow_up_date or 'None'} to {data.follow_up_date or 'None'}",
                request=request
            )
        lead.follow_up_date = data.follow_up_date
        lead.last_updated_by = user

    # 4. Lead Assigned (assigned_to changes, or salesman_name changes)
    if data.assigned_to is not None and data.assigned_to != lead.assigned_to:
        log_lead_activity(db, lead.id, lead.lead_number, user, role, "Lead Assigned", lead.assigned_to or "Unassigned", data.assigned_to or "Unassigned")
        lead.assigned_to = data.assigned_to
        lead.last_updated_by = user
        lead.current_owner = data.assigned_to

        # Notify new assignee and admin
        from models import create_notification
        msg = f"Lead {lead.customer_name} (#{lead.lead_number}) has been assigned to you by {user}."
        if data.assigned_to:
            create_notification(db, message=msg, type="Assignment Changed", user_id=data.assigned_to, lead_id=lead.id)
        create_notification(db, message=f"Lead {lead.customer_name} assignment changed to {data.assigned_to or 'Unassigned'}", type="Assignment Changed", role="admin", lead_id=lead.id)

    if getattr(data, "salesman_name", None) is not None and data.salesman_name != lead.salesman_name:
        log_lead_activity(db, lead.id, lead.lead_number, user, role, "Lead Assigned", lead.salesman_name or "Unassigned", data.salesman_name or "Unassigned")
        lead.salesman_name = data.salesman_name
        lead.last_updated_by = user
        lead.current_owner = data.salesman_name

        # Notify new salesman and admin
        from models import create_notification
        msg = f"Lead {lead.customer_name} (#{lead.lead_number}) has been assigned to you by {user}."
        if data.salesman_name:
            create_notification(db, message=msg, type="Assignment Changed", user_id=data.salesman_name, lead_id=lead.id)
        create_notification(db, message=f"Lead {lead.customer_name} salesman assignment changed to {data.salesman_name or 'Unassigned'}", type="Assignment Changed", role="admin", lead_id=lead.id)

    # 5. Photo Uploaded
    if data.photo is not None and data.photo != lead.photo and data.photo != "HAS_PHOTO" and data.photo != "":
        log_lead_activity(db, lead.id, lead.lead_number, user, role, "Photo Uploaded", "", data.photo)
        if role.lower() == "salesman":
            log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Shop Photo Uploaded", new_value=data.photo, request=request)
        lead.photo = data.photo
        lead.last_updated_by = user

    media_changed = False
    
    # 6. Store Images JSON Changed
    if data.store_images_json is not None and data.store_images_json != lead.store_images_json:
        try:
            old_imgs = json.loads(lead.store_images_json or "[]")
            new_imgs = json.loads(data.store_images_json or "[]")
            added = [x for x in new_imgs if x not in old_imgs]
            deleted = [x for x in old_imgs if x not in new_imgs]
            
            if added:
                log_lead_activity(db, lead.id, lead.lead_number, user, role, "Media Uploaded", "", f"Uploaded {len(added)} store image{'s' if len(added) > 1 else ''}.")
                if role.lower() == "salesman":
                    log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Store Media Uploaded", remark=f"Uploaded {len(added)} store image{'s' if len(added) > 1 else ''}.", request=request)
            if deleted:
                log_lead_activity(db, lead.id, lead.lead_number, user, role, "Media Deleted", "", f"Deleted {len(deleted)} image{'s' if len(deleted) > 1 else ''}.")
                if role.lower() == "salesman":
                    log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Store Media Deleted", remark=f"Deleted {len(deleted)} image{'s' if len(deleted) > 1 else ''}.", request=request)
        except Exception as e:
            logger.error(f"Error logging store images change: {e}")
            
        lead.store_images_json = data.store_images_json
        lead.last_updated_by = user
        media_changed = True

    # 7. Store Videos JSON Changed
    if data.store_videos_json is not None and data.store_videos_json != lead.store_videos_json:
        try:
            old_vids = json.loads(lead.store_videos_json or "[]")
            new_vids = json.loads(data.store_videos_json or "[]")
            added = [x for x in new_vids if x not in old_vids]
            deleted = [x for x in old_vids if x not in new_vids]
            
            if added:
                log_lead_activity(db, lead.id, lead.lead_number, user, role, "Media Uploaded", "", f"Uploaded {len(added)} store video{'s' if len(added) > 1 else ''}.")
                if role.lower() == "salesman":
                    log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Store Media Uploaded", remark=f"Uploaded {len(added)} store video{'s' if len(added) > 1 else ''}.", request=request)
            if deleted:
                log_lead_activity(db, lead.id, lead.lead_number, user, role, "Media Deleted", "", f"Deleted {len(deleted)} video{'s' if len(deleted) > 1 else ''}.")
                if role.lower() == "salesman":
                    log_salesman_activity(db, lead_id=lead.id, salesman_name=user, activity_type="Store Media Deleted", remark=f"Deleted {len(deleted)} video{'s' if len(deleted) > 1 else ''}.", request=request)
        except Exception as e:
            logger.error(f"Error logging store videos change: {e}")
            
        lead.store_videos_json = data.store_videos_json
        lead.last_updated_by = user
        media_changed = True

    # Copy remaining fields
    exclude_fields = {"edited_by_name", "edited_by_role", "status", "remarks", "follow_up_date", "assigned_to", "salesman_name", "photo", "store_images_json", "store_videos_json"}
    for field, val in data.model_dump(exclude_none=True).items():
        if field not in exclude_fields:
            if field == "phone":
                val = normalize_phone(val) if val else ""
            setattr(lead, field, val)

    lead.updated_at = int(time.time() * 1000)
    db.commit()
    db.refresh(lead)
    
    lead_data = {
        "id": lead.id,
        "lead_number": lead.lead_number,
        "salesman_id": lead.salesman_id,
        "salesman_name": lead.salesman_name,
        "customer_name": lead.customer_name,
        "phone": lead.phone,
        "shop_name": lead.shop_name,
        "address": lead.address,
        "city": lead.city,
        "pincode": lead.pincode,
        "business_type": lead.business_type,
        "remarks": lead.remarks,
        "follow_up_date": lead.follow_up_date,
        "latitude": lead.latitude,
        "longitude": lead.longitude,
        "photo": lead.photo,
        "status": lead.status,
        "lead_source": lead.lead_source,
        "assigned_to": lead.assigned_to,
        "created_by": lead.created_by,
        "current_owner": lead.current_owner,
        "last_updated_by": lead.last_updated_by,
        "created_note": lead.created_note,
        "created_note_by": lead.created_note_by,
        "created_note_date": lead.created_note_date,
        "created_note_time": lead.created_note_time,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "store_images_json": lead.store_images_json,
        "store_videos_json": lead.store_videos_json,
        "store_width": lead.store_width,
        "store_length": lead.store_length,
        "store_height": lead.store_height,
        "store_area": lead.store_area,
    }

    
    from websocket_manager import broadcast_event
    broadcast_event("lead_updated", lead_data)
    
    if media_changed:
        broadcast_event("lead_media_updated", {
            "lead_id": lead.id,
            "salesman_id": lead.salesman_id,
            "assigned_to": lead.assigned_to,
            "store_images_json": lead.store_images_json,
            "store_videos_json": lead.store_videos_json
        })
    
    if status_changed:
        broadcast_event("status_changed", {
            "lead_id": lead.id,
            "salesman_id": lead.salesman_id,
            "assigned_to": lead.assigned_to,
            "old_status": old_status,
            "new_status": lead.status
        })
        
    if followup_changed:
        broadcast_event("followup_changed", {
            "lead_id": lead.id,
            "salesman_id": lead.salesman_id,
            "assigned_to": lead.assigned_to,
            "follow_up_date": lead.follow_up_date
        })
        
    if remark_added:
        broadcast_event("remark_added", {
            "lead_id": lead.id,
            "salesman_id": lead.salesman_id,
            "assigned_to": lead.assigned_to,
            "remark": remark_msg
        })
        
    return lead


@router.get("/{lead_id}", response_model=schemas.LeadOut)
def get_lead(lead_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    return lead


@router.delete("/{lead_id}")
def delete_lead(lead_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead_id_to_delete = lead.id
    lead_salesman_id = lead.salesman_id
    lead_assigned_to = lead.assigned_to
    
    # Cascade delete related entries
    db.query(models.LeadFollowup).filter(models.LeadFollowup.lead_id == lead_id).delete()
    db.query(models.FollowupHistory).filter(models.FollowupHistory.lead_id == lead_id).delete()
    db.query(models.LeadActivity).filter(models.LeadActivity.lead_id == lead_id).delete()
    db.query(models.SalesmanActivityLog).filter(models.SalesmanActivityLog.lead_id == lead_id).delete()
    db.query(models.TelecallerActivityLog).filter(models.TelecallerActivityLog.lead_id == lead_id).delete()
    
    db.delete(lead)
    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("lead_deleted", {
        "id": lead_id_to_delete,
        "salesman_id": lead_salesman_id,
        "assigned_to": lead_assigned_to
    })
    
    return {"status": "deleted"}


from pydantic import BaseModel

class LogCallRequest(BaseModel):
    username: str
    role: str


@router.get("/{lead_id}/activities", response_model=list[schemas.LeadActivityOut])
def get_lead_activities(lead_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Fetch all activities for a lead sorted by newest first."""
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    return db.query(models.LeadActivity).filter(models.LeadActivity.lead_id == lead_id).order_by(models.LeadActivity.created_at.desc()).all()


@router.post("/{lead_id}/log-call")
def log_lead_call(lead_id: str, payload: LogCallRequest, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Logs a call click action to lead activities."""
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    username = current_user.username
    role = current_user.role
    from models import log_lead_activity, log_telecaller_activity, log_salesman_activity
    log_lead_activity(db, lead.id, lead.lead_number, username, role, "Call Made", "", lead.customer_name)
    if role.lower() == "salesman":
        log_salesman_activity(db, lead_id=lead.id, salesman_name=username, activity_type="Call Made", remark="Outbound call initiated.", request=request)
    else:
        log_telecaller_activity(db, lead_id=lead.id, telecaller_name=username, action_type="Call Started", remark="Outbound call initiated.", request=request)
    db.commit()
    return {"status": "logged"}


@router.post("/{lead_id}/log-whatsapp")
def log_lead_whatsapp(lead_id: str, payload: LogCallRequest, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Logs a WhatsApp click action to lead activities."""
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    username = current_user.username
    role = current_user.role
    from models import log_lead_activity, log_telecaller_activity, log_salesman_activity
    log_lead_activity(db, lead.id, lead.lead_number, username, role, "WhatsApp Opened", "", lead.customer_name)
    if role.lower() == "salesman":
        log_salesman_activity(db, lead_id=lead.id, salesman_name=username, activity_type="WhatsApp Opened", remark="WhatsApp chat opened.", request=request)
    else:
        log_telecaller_activity(db, lead_id=lead.id, telecaller_name=username, action_type="WhatsApp", remark="WhatsApp chat opened.", request=request)
    db.commit()
    return {"status": "logged"}


class RemarkRequest(BaseModel):
    username: str
    role: str
    remark: str


@router.post("/{lead_id}/remark")
def add_lead_remark(lead_id: str, payload: RemarkRequest, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Saves a permanent remark into LeadActivity as action='Remark'. Never overwritten."""
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    if not payload.remark or not payload.remark.strip():
        raise HTTPException(status_code=400, detail="Remark text cannot be empty")
    username = current_user.username
    role = current_user.role
    from models import log_lead_activity, log_telecaller_activity, log_salesman_activity
    activity = log_lead_activity(
        db, lead.id, lead.lead_number,
        username, role,
        "Remark", "", payload.remark.strip()
    )
    if role.lower() == "salesman":
        log_salesman_activity(db, lead_id=lead.id, salesman_name=username, activity_type="General Note", remark=payload.remark.strip(), request=request)
    else:
        log_telecaller_activity(db, lead_id=lead.id, telecaller_name=username, action_type="Remark Added", remark=payload.remark.strip(), request=request)
    
    # Notify assigned user, salesman, and admin about new remark
    from models import create_notification
    msg = f"New remark added for {lead.customer_name} by {username} ({role}): {payload.remark.strip()}"
    if lead.assigned_to and lead.assigned_to != username:
        create_notification(db, message=msg, type="New Followup", user_id=lead.assigned_to, lead_id=lead.id)
    if lead.salesman_name and lead.salesman_name != username:
        create_notification(db, message=msg, type="New Followup", user_id=lead.salesman_name, lead_id=lead.id)
    create_notification(db, message=msg, type="New Followup", role="admin", lead_id=lead.id)

    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("remark_added", {
        "lead_id": lead.id,
        "salesman_id": lead.salesman_id,
        "assigned_to": lead.assigned_to,
        "remark": payload.remark.strip()
    })
    
    return {"status": "saved", "activity_id": activity.id}


@router.post("/{lead_id}/log-location-viewed")
def log_lead_location_viewed(lead_id: str, payload: LogCallRequest, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    username = current_user.username
    role = current_user.role
    from models import log_lead_activity, log_telecaller_activity
    log_lead_activity(db, lead.id, lead.lead_number, username, role, "Location Viewed", "", lead.customer_name)
    log_telecaller_activity(db, lead_id=lead.id, telecaller_name=username, action_type="Location", remark="Location GPS map viewed.", request=request)
    db.commit()
    return {"status": "logged"}


@router.post("/{lead_id}/log-photo-viewed")
def log_lead_photo_viewed(lead_id: str, payload: LogCallRequest, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    username = current_user.username
    role = current_user.role
    from models import log_lead_activity, log_telecaller_activity
    log_lead_activity(db, lead.id, lead.lead_number, username, role, "Photo Viewed", "", lead.customer_name)
    log_telecaller_activity(db, lead_id=lead.id, telecaller_name=username, action_type="Photo", remark="Site visit photo viewed.", request=request)
    db.commit()
    return {"status": "logged"}


@router.get("/{lead_id}/remarks", response_model=list[schemas.LeadActivityOut])
def get_lead_remarks(lead_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Returns all remark entries for a lead (action='Remark'), newest first."""
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    check_lead_permission(lead, current_user)
    return (
        db.query(models.LeadActivity)
        .filter(
            models.LeadActivity.lead_id == lead_id,
            models.LeadActivity.action == "Remark"
        )
        .order_by(models.LeadActivity.created_at.desc())
        .all()
    )
