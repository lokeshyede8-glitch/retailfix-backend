import uuid
import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from auth_utils import get_current_user, CurrentUser, hash_password, RoleChecker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/factory-users", tags=["factory-users"])


@router.get("", response_model=list[schemas.FactoryUserOut])
def list_factory_users(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"]))
):
    """Admin: sabhi factory users ki list lao."""
    users = (
        db.query(models.User)
        .filter(models.User.role == "factory")
        .order_by(models.User.created_at.desc())
        .all()
    )
    result = []
    for u in users:
        result.append(schemas.FactoryUserOut(
            id=u.id,
            name=u.username or u.email,
            email=u.email or "",
            phone=u.mobile or "",
            employee_id=u.employee_id or "",
            username=u.username or "",
            is_active=u.is_active,
            created_at=u.created_at or 0,
        ))
    return result


@router.post("", response_model=schemas.FactoryUserOut)
def create_factory_user(
    data: schemas.FactoryUserCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"]))
):
    """Admin: naya factory user banao."""
    # Email unique check
    existing_email = db.query(models.User).filter(models.User.email == data.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Employee ID unique check
    emp_id = data.employee_id.strip()
    if not emp_id:
        raise HTTPException(status_code=400, detail="Employee ID is required")
    existing_emp = db.query(models.User).filter(models.User.employee_id == emp_id).first()
    if existing_emp:
        raise HTTPException(status_code=400, detail="Employee ID already exists")

    # Phone unique check (agar diya gaya ho)
    phone_val = (data.phone or "").strip()
    if phone_val:
        existing_phone = db.query(models.User).filter(models.User.mobile == phone_val).first()
        if existing_phone:
            raise HTTPException(status_code=400, detail="Phone number already registered")

    # Password match check
    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    # Password strength check
    from auth_utils import validate_password_strength
    try:
        validate_password_strength(data.password)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    user_id = str(uuid.uuid4())
    hashed_pass = hash_password(data.password)
    now_ms = int(time.time() * 1000)

    # Username: name se generate karo (spaces → underscores, lowercase)
    clean_uname = data.name.strip().replace(" ", "_").lower()
    uname_check = db.query(models.User).filter(models.User.username == clean_uname).first()
    if uname_check:
        clean_uname = f"{clean_uname}_{user_id[:4]}"

    user_record = models.User(
        id=user_id,
        employee_id=emp_id,
        username=clean_uname,
        email=data.email,
        mobile=phone_val if phone_val else None,
        password_hash=hashed_pass,
        role="factory",
        is_active=True,
        must_change_password=False,
        created_at=now_ms,
        updated_at=now_ms,
    )
    db.add(user_record)
    db.commit()
    db.refresh(user_record)

    logger.info("Factory user created: %s (%s)", clean_uname, emp_id)

    return schemas.FactoryUserOut(
        id=user_record.id,
        name=data.name,
        email=user_record.email or "",
        phone=user_record.mobile or "",
        employee_id=user_record.employee_id or "",
        username=user_record.username or "",
        is_active=user_record.is_active,
        created_at=user_record.created_at,
    )


@router.put("/{user_id}", response_model=schemas.FactoryUserOut)
def update_factory_user(
    user_id: str,
    data: schemas.FactoryUserUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"]))
):
    """Admin: factory user update karo (name, email, password, active status)."""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.role == "factory"
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Factory user not found")

    data_dict = data.model_dump(exclude_none=True)

    # Password update
    if data_dict.get("password"):
        if data_dict.get("password") != data_dict.get("confirm_password"):
            raise HTTPException(status_code=400, detail="Passwords do not match")
        from auth_utils import validate_password_strength
        try:
            validate_password_strength(data_dict["password"])
        except ValueError as val_err:
            raise HTTPException(status_code=400, detail=str(val_err))
        user.password_hash = hash_password(data_dict["password"])

    if data_dict.get("name"):
        user.username = data_dict["name"].strip().replace(" ", "_").lower()

    if data_dict.get("email"):
        # Email unique check (sirf agar change hua ho)
        if data_dict["email"] != user.email:
            existing = db.query(models.User).filter(models.User.email == data_dict["email"]).first()
            if existing:
                raise HTTPException(status_code=400, detail="Email already registered")
        user.email = data_dict["email"]

    if data_dict.get("phone") is not None:
        user.mobile = data_dict["phone"] or None

    if "is_active" in data_dict:
        user.is_active = data_dict["is_active"]

    user.updated_at = int(time.time() * 1000)
    db.commit()
    db.refresh(user)

    return schemas.FactoryUserOut(
        id=user.id,
        name=user.username or "",
        email=user.email or "",
        phone=user.mobile or "",
        employee_id=user.employee_id or "",
        username=user.username or "",
        is_active=user.is_active,
        created_at=user.created_at or 0,
    )


@router.delete("/{user_id}")
def delete_factory_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"]))
):
    """Admin: factory user ko deactivate karo (soft delete)."""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.role == "factory"
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Factory user not found")

    # Sabhi active sessions revoke karo
    db.query(models.UserSession).filter(
        models.UserSession.user_id == user_id,
        models.UserSession.is_revoked == False
    ).update({"is_revoked": True})

    user.is_active = False
    user.updated_at = int(time.time() * 1000)
    db.commit()

    logger.info("Factory user deactivated: %s", user_id)
    return {"message": "Factory user deactivated successfully"}
