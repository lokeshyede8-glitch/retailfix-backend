import uuid
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database import get_db
import models
import schemas
from auth_utils import get_current_user, CurrentUser, verify_password, hash_password, RoleChecker

router = APIRouter(prefix="/telecallers", tags=["telecallers"])


@router.get("", response_model=list[schemas.TelecallerOut])
def list_telecallers(db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    from sqlalchemy import func
    telecallers = db.query(models.Telecaller).order_by(models.Telecaller.name).all()
    lead_counts_raw = (
        db.query(models.Lead.assigned_to, func.count(models.Lead.id).label("cnt"))
        .group_by(models.Lead.assigned_to)
        .all()
    )
    lead_counts = {row.assigned_to: row.cnt for row in lead_counts_raw if row.assigned_to}
    
    result = []
    for t in telecallers:
        result.append(schemas.TelecallerOut(
            id=t.id,
            name=t.name,
            phone=t.phone,
            email=t.email,
            active=t.active,
            created_at=t.created_at,
            lead_count=lead_counts.get(t.name, 0),
        ))
    return result


@router.post("", response_model=schemas.TelecallerOut)
def create_telecaller(data: schemas.TelecallerCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
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

    t_id = str(uuid.uuid4())
    hashed_pass = hash_password(data.password)
    phone_stored = phone_val if phone_val else None
    
    t = models.Telecaller(
        id=t_id,
        name=data.name,
        phone=phone_stored or "",
        email=data.email,
        pin=hashed_pass,
        active=True,
        created_at=int(time.time() * 1000),
    )
    db.add(t)
    
    clean_uname = data.name.strip().replace(" ", "_").lower()
    uname_check = db.query(models.User).filter(models.User.username == clean_uname).first()
    if uname_check:
        clean_uname = f"{clean_uname}_{t_id[:4]}"
        
    user_record = models.User(
        id=t_id,
        employee_id=emp_id,
        username=clean_uname,
        email=data.email,
        mobile=phone_stored,
        password_hash=hashed_pass,
        role="telecaller",
        is_active=True,
        must_change_password=False,
        created_at=t.created_at,
        updated_at=t.created_at
    )
    db.add(user_record)
    
    db.commit()
    db.refresh(t)
    
    tc_data = {
        "id": t.id,
        "name": t.name,
        "phone": t.phone,
        "email": t.email,
        "active": t.active,
        "created_at": t.created_at,
        "lead_count": 0
    }
    from websocket_manager import broadcast_event
    broadcast_event("telecaller_created", tc_data)
    
    return schemas.TelecallerOut(
        id=t.id,
        name=t.name,
        phone=t.phone,
        email=t.email,
        active=t.active,
        created_at=t.created_at,
        lead_count=0,
    )


@router.put("/{telecaller_id}", response_model=schemas.TelecallerOut)
def update_telecaller(telecaller_id: str, data: schemas.TelecallerUpdate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    t = db.query(models.Telecaller).filter(models.Telecaller.id == telecaller_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Telecaller not found")
    old_name = t.name
    new_name = data.name
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
        t.pin = hashed_pass
    elif "pin" in data_dict and data_dict["pin"]:
        hashed_pass = hash_password(data_dict["pin"])
        t.pin = hashed_pass
    else:
        hashed_pass = None

    for field, val in data_dict.items():
        if field in ["password", "confirm_password", "pin"]:
            continue
        setattr(t, field, val)
        
    if new_name and new_name != old_name:
        db.query(models.Lead).filter(models.Lead.assigned_to == old_name).update({models.Lead.assigned_to: new_name})
        
    user = db.query(models.User).filter(models.User.id == t.id).first()
    if user:
        if data.active is not None:
            user.is_active = data.active
        if data.phone is not None:
            user.mobile = data.phone
        if data.email is not None:
            existing_email = db.query(models.User).filter(models.User.email == data.email, models.User.id != t.id).first()
            if existing_email:
                raise HTTPException(status_code=400, detail="Email already registered")
            user.email = data.email
        if hashed_pass is not None:
            user.password_hash = hashed_pass
            user.must_change_password = False
        if data.name is not None:
            clean_uname = data.name.strip().replace(" ", "_").lower()
            uname_check = db.query(models.User).filter(models.User.username == clean_uname, models.User.id != t.id).first()
            if uname_check:
                clean_uname = f"{clean_uname}_{t.id[:4]}"
            user.username = clean_uname
        user.updated_at = int(time.time() * 1000)
        
    db.commit()
    db.refresh(t)
    count = db.query(models.Lead).filter(models.Lead.assigned_to == t.name).count()
    
    tc_data = {
        "id": t.id,
        "name": t.name,
        "phone": t.phone,
        "email": t.email,
        "active": t.active,
        "created_at": t.created_at,
        "lead_count": count
    }
    from websocket_manager import broadcast_event
    broadcast_event("telecaller_updated", tc_data)
    
    return schemas.TelecallerOut(
        id=t.id,
        name=t.name,
        phone=t.phone,
        email=t.email,
        active=t.active,
        created_at=t.created_at,
        lead_count=count,
    )


@router.delete("/{telecaller_id}")
def delete_telecaller(telecaller_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    t = db.query(models.Telecaller).filter(models.Telecaller.id == telecaller_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Telecaller not found")
    t_id = t.id
    
    # Unassign leads and followups from this telecaller name
    db.query(models.Lead).filter(models.Lead.assigned_to == t.name).update({
        models.Lead.assigned_to: "",
        models.Lead.current_owner: ""
    })
    db.query(models.LeadFollowup).filter(models.LeadFollowup.assigned_to == t.name).update({
        models.LeadFollowup.assigned_to: ""
    })
    
    user = db.query(models.User).filter(models.User.id == t.id).first()
    if user:
        db.delete(user)
        
    db.delete(t)
    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("telecaller_deleted", {"id": t_id})
    
    return {"status": "deleted"}


@router.post("/login", response_model=schemas.TelecallerOut)
def telecaller_login(data: schemas.TelecallerLogin, db: Session = Depends(get_db)):
    raise HTTPException(status_code=410, detail="This endpoint has been deprecated. Please use unified login at /auth/login")


@router.get("/{telecaller_name}/updates")
def get_telecaller_updates(telecaller_name: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "salesman":
        raise HTTPException(status_code=403, detail="Forbidden")
    if role_lower == "telecaller" and current_user.username != telecaller_name:
        raise HTTPException(status_code=403, detail="Forbidden")
    # Fetch recent activities performed by this telecaller
    activities = (db.query(models.LeadActivity)
                  .filter(models.LeadActivity.username == telecaller_name)
                  .order_by(models.LeadActivity.created_at.desc())
                  .limit(100)
                  .all())
    # Fetch leads assigned to this telecaller
    leads = (db.query(models.Lead)
             .filter(models.Lead.assigned_to == telecaller_name)
             .order_by(models.Lead.updated_at.desc())
             .all())
    
    return {
        "activities": [
            {
                "id": a.id,
                "lead_id": a.lead_id,
                "lead_number": a.lead_number,
                "date": a.date,
                "time": a.time,
                "action": a.action,
                "old_value": a.old_value,
                "new_value": a.new_value,
                "created_at": a.created_at
            }
            for a in activities
        ],
        "leads": [
            {
                "id": l.id,
                "lead_number": l.lead_number,
                "customer_name": l.customer_name,
                "phone": l.phone,
                "status": l.status,
                "business_type": l.business_type,
                "city": l.city,
                "follow_up_date": l.follow_up_date,
                "updated_at": l.updated_at
            }
            for l in leads
        ]
    }


class LogActivityRequest(BaseModel):
    lead_id: str
    telecaller_name: str
    action_type: str # Call / WhatsApp / Remark / Follow-up / Status / Location / Photo
    old_value: Optional[str] = ""
    new_value: Optional[str] = ""
    remark: Optional[str] = ""


@router.post("/activity/log")
def create_activity_log(payload: LogActivityRequest, request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == payload.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    role_lower = current_user.role.lower()
    if role_lower == "telecaller" and lead.assigned_to != current_user.username and lead.current_owner != current_user.username:
        raise HTTPException(status_code=403, detail="Forbidden")
    elif role_lower == "salesman":
        raise HTTPException(status_code=403, detail="Forbidden")
    from models import log_telecaller_activity
    log_telecaller_activity(
        db,
        lead_id=payload.lead_id,
        telecaller_name=payload.telecaller_name,
        action_type=payload.action_type,
        old_value=payload.old_value,
        new_value=payload.new_value,
        remark=payload.remark,
        request=request
    )
    db.commit()
    return {"status": "logged"}


@router.get("/activity/logs")
def get_all_activity_logs(lead_id: Optional[str] = None, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower == "salesman":
        raise HTTPException(status_code=403, detail="Forbidden")
        
    query = db.query(models.TelecallerActivityLog)
    
    if lead_id:
        lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        if role_lower == "telecaller" and lead.assigned_to != current_user.username and lead.current_owner != current_user.username:
            raise HTTPException(status_code=403, detail="Forbidden")
        query = query.filter(models.TelecallerActivityLog.lead_id == lead_id)
    else:
        if role_lower == "telecaller":
            query = query.filter(models.TelecallerActivityLog.username == current_user.username)
        elif role_lower != "admin":
            raise HTTPException(status_code=403, detail="Forbidden")
            
    logs = query.order_by(models.TelecallerActivityLog.created_at.desc()).all()
    return logs


# IMPORTANT: specific paths like /activity/logs/{lead_id} must come BEFORE /{telecaller_id}
@router.get("/activity/logs/{lead_id}")
def get_activity_logs_for_lead(lead_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    lead = db.query(models.Lead).filter(models.Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    role_lower = current_user.role.lower()
    if role_lower == "salesman" and lead.salesman_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    elif role_lower == "telecaller" and lead.assigned_to != current_user.username and lead.current_owner != current_user.username:
        raise HTTPException(status_code=403, detail="Forbidden")
    logs = (db.query(models.TelecallerActivityLog)
            .filter(models.TelecallerActivityLog.lead_id == lead_id)
            .order_by(models.TelecallerActivityLog.created_at.desc())
            .all())
    return logs


@router.get("/{telecaller_id}", response_model=schemas.TelecallerOut)
def get_telecaller(telecaller_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    t = db.query(models.Telecaller).filter(models.Telecaller.id == telecaller_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Telecaller not found")
    if role_lower == "telecaller" and current_user.id != t.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    lead_count = db.query(models.Lead).filter(models.Lead.assigned_to == t.name).count()
    return schemas.TelecallerOut(
        id=t.id,
        name=t.name,
        phone=t.phone,
        email=t.email,
        active=t.active,
        created_at=t.created_at,
        lead_count=lead_count,
    )
