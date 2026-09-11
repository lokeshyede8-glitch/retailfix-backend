import uuid
import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
import models
import schemas
from auth_utils import get_current_user, RoleChecker, CurrentUser, verify_password, hash_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/salesmen", tags=["salesmen"])


@router.get("", response_model=list[schemas.SalesmanOut])
def list_salesmen(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    t0 = time.perf_counter()

    salesmen = db.query(models.Salesman).order_by(models.Salesman.name).all()

    # ── Single aggregated count — replaces one query per salesman ────────────
    lead_counts_raw = (
        db.query(models.Lead.salesman_id, func.count(models.Lead.id).label("cnt"))
        .group_by(models.Lead.salesman_id)
        .all()
    )
    lead_counts = {row.salesman_id: row.cnt for row in lead_counts_raw}

    result = [
        schemas.SalesmanOut(
            id=s.id, name=s.name, phone=s.phone, email=s.email, area=s.area,
            active=s.active, created_at=s.created_at,
            lead_count=lead_counts.get(s.id, 0),
        )
        for s in salesmen
    ]

    logger.info("GET /salesmen  rows=%d  %.0fms", len(result), (time.perf_counter() - t0) * 1000)
    return result


@router.post("", response_model=schemas.SalesmanOut)
def create_salesman(data: schemas.SalesmanCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
        # Validate unique email
    existing_email = db.query(models.User).filter(models.User.email == data.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    emp_id = data.employee_id.strip()
    if not emp_id:
        raise HTTPException(status_code=400, detail="Employee ID is required")
    existing_emp = db.query(models.User).filter(models.User.employee_id == emp_id).first()
    if existing_emp:
        raise HTTPException(status_code=400, detail="Employee ID already exists")

    # Validate unique phone (only if non-empty)
    phone_val = (data.phone or "").strip()
    if phone_val:
        existing_phone = db.query(models.User).filter(models.User.mobile == phone_val).first()
        if existing_phone:
            raise HTTPException(status_code=400, detail="Phone number already registered")

    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    from auth_utils import validate_password_strength
    try:
        validate_password_strength(data.password)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    s_id = str(uuid.uuid4())
    hashed_pass = hash_password(data.password)
    phone_stored = phone_val if phone_val else None
    
    s = models.Salesman(
        id=s_id,
        name=data.name,
        phone=phone_stored or "",
        email=data.email,
        pin=hashed_pass,
        area=data.area or "",
        active=True,
        created_at=int(time.time() * 1000),
    )
    db.add(s)
    
    clean_uname = data.name.strip().replace(" ", "_").lower()
    uname_check = db.query(models.User).filter(models.User.username == clean_uname).first()
    if uname_check:
        clean_uname = f"{clean_uname}_{s_id[:4]}"
        
    user_record = models.User(
        id=s_id,
        employee_id=emp_id,
        username=clean_uname,
        email=data.email,
        mobile=phone_stored,
        password_hash=hashed_pass,
        role="salesman",
        is_active=True,
        must_change_password=False,
        created_at=s.created_at,
        updated_at=s.created_at
    )
    db.add(user_record)
    
    db.commit()
    db.refresh(s)
    
    sm_data = {
        "id": s.id,
        "name": s.name,
        "phone": s.phone,
        "email": s.email,
        "area": s.area,
        "active": s.active,
        "created_at": s.created_at,
        "lead_count": 0
    }
    from websocket_manager import broadcast_event
    broadcast_event("salesman_created", sm_data)
    
    return schemas.SalesmanOut(id=s.id, name=s.name, phone=s.phone, email=s.email,
                               area=s.area, active=s.active,
                               created_at=s.created_at, lead_count=0)


@router.put("/{salesman_id}", response_model=schemas.SalesmanOut)
def update_salesman(salesman_id: str, data: schemas.SalesmanUpdate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    s = db.query(models.Salesman).filter(models.Salesman.id == salesman_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Salesman not found")
    data_dict = data.model_dump(exclude_none=True)
    
    # Handle password validation if password is provided
    if "password" in data_dict and data_dict["password"]:
        if data_dict.get("password") != data_dict.get("confirm_password"):
            raise HTTPException(status_code=400, detail="Passwords do not match")
        
        from auth_utils import validate_password_strength
        try:
            validate_password_strength(data_dict["password"])
        except ValueError as val_err:
            raise HTTPException(status_code=400, detail=str(val_err))
            
        hashed_pass = hash_password(data_dict["password"])
        s.pin = hashed_pass
    elif "pin" in data_dict and data_dict["pin"]:
        hashed_pass = hash_password(data_dict["pin"])
        s.pin = hashed_pass
    else:
        hashed_pass = None

    for field, val in data_dict.items():
        if field in ["password", "confirm_password", "pin"]:
            continue
        setattr(s, field, val)
        
    user = db.query(models.User).filter(models.User.id == s.id).first()
    if user:
        if data.active is not None:
            user.is_active = data.active
        if data.phone is not None:
            user.mobile = data.phone
        if data.email is not None:
            existing_email = db.query(models.User).filter(models.User.email == data.email, models.User.id != s.id).first()
            if existing_email:
                raise HTTPException(status_code=400, detail="Email already registered")
            user.email = data.email
        if hashed_pass is not None:
            user.password_hash = hashed_pass
            user.must_change_password = False
        if data.name is not None:
            clean_uname = data.name.strip().replace(" ", "_").lower()
            uname_check = db.query(models.User).filter(models.User.username == clean_uname, models.User.id != s.id).first()
            if uname_check:
                clean_uname = f"{clean_uname}_{s.id[:4]}"
            user.username = clean_uname
        user.updated_at = int(time.time() * 1000)
        
    db.commit()
    db.refresh(s)
    lead_count = db.query(func.count(models.Lead.id)).filter(models.Lead.salesman_id == s.id).scalar()
    
    sm_data = {
        "id": s.id,
        "name": s.name,
        "phone": s.phone,
        "email": s.email,
        "area": s.area,
        "active": s.active,
        "created_at": s.created_at,
        "lead_count": lead_count or 0
    }
    from websocket_manager import broadcast_event
    broadcast_event("salesman_updated", sm_data)
    
    return schemas.SalesmanOut(id=s.id, name=s.name, phone=s.phone, email=s.email,
                               area=s.area, active=s.active,
                               created_at=s.created_at, lead_count=lead_count or 0)


@router.delete("/{salesman_id}")
def delete_salesman(salesman_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    s = db.query(models.Salesman).filter(models.Salesman.id == salesman_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Salesman not found")
    s_id = s.id
    
    # Reassign leads to Unassigned
    db.query(models.Lead).filter(models.Lead.salesman_id == salesman_id).update({
        models.Lead.salesman_id: "",
        models.Lead.salesman_name: "Unassigned",
        models.Lead.current_owner: "Unassigned"
    })
    
    user = db.query(models.User).filter(models.User.id == s.id).first()
    if user:
        db.delete(user)
        
    db.delete(s)
    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("salesman_deleted", {"id": s_id})
    
    return {"status": "deleted"}





from typing import Optional
from fastapi import Request
from pydantic import BaseModel

class SalesmanActivityCreatePayload(BaseModel):
    salesman_name: str
    activity_type: str
    old_value: str = ""
    new_value: str = ""
    remark: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None

@router.post("/activity/log/{lead_id}")
def log_salesman_activity_endpoint(lead_id: str, payload: SalesmanActivityCreatePayload, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    role_lower = current_user.role.lower()
    if role_lower == "salesman" and lead.salesman_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    elif role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    from models import log_salesman_activity
    log_entry = log_salesman_activity(
        db,
        lead_id=lead_id,
        salesman_name=payload.salesman_name,
        activity_type=payload.activity_type,
        old_value=payload.old_value,
        new_value=payload.new_value,
        remark=payload.remark,
        latitude=payload.latitude,
        longitude=payload.longitude,
        request=request
    )
    db.commit()
    return {"status": "logged", "id": log_entry.id}

@router.get("/activity/logs/{lead_id}")
def get_salesman_activity_logs_for_lead(lead_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    role_lower = current_user.role.lower()
    if role_lower == "salesman" and lead.salesman_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    elif role_lower == "telecaller":
        if lead.assigned_to != current_user.username and lead.current_owner != current_user.username:
            raise HTTPException(status_code=403, detail="Forbidden")
            
    logs = (db.query(models.SalesmanActivityLog)
            .filter(models.SalesmanActivityLog.lead_id == lead_id)
            .order_by(models.SalesmanActivityLog.created_at.desc())
            .all())
    return logs

