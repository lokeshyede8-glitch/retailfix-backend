import json
import os
import shutil
import time
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict

from database import get_db
import models
from auth_utils import get_current_user, RoleChecker, CurrentUser

router = APIRouter(prefix="/settings", tags=["Settings"])
logger = logging.getLogger(__name__)

TERMS_KEY = "default_terms"

DEFAULT_TERMS = [
    "Prices are factory rates — no middlemen, no hidden costs.",
    "50% advance payment required to confirm order; balance before/at delivery.",
    "Delivery: 7–15 working days from order confirmation, depending on quantity & customization.",
    "GST as applicable will be charged extra unless already included above.",
    "Installation support available on request.",
    "Quotation valid for 15 days from the date of issue.",
]


def _get_or_init_terms(db: Session) -> list:
    """Return the stored terms, seeding defaults if the table is empty."""
    rows = db.query(models.QuotationTerm).filter(models.QuotationTerm.is_enabled == True).order_by(models.QuotationTerm.display_order.asc()).all()
    return [r.text for r in rows]


def _upsert_setting(db: Session, key: str, value: str):
    """Insert or update a setting by key."""
    row = db.query(models.AppSettings).filter(models.AppSettings.key == key).first()
    if row is None:
        row = models.AppSettings(key=key, value=value)
        db.add(row)
    else:
        row.value = value


# ── Schema ────────────────────────────────────────────────────────────────────

class TermsPayload(BaseModel):
    terms: List[str]


class KVPayload(BaseModel):
    value: str


class BulkSettingsPayload(BaseModel):
    settings: Dict[str, str]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/terms")
def get_terms(db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    """Return the current default Terms & Conditions list."""
    terms = _get_or_init_terms(db)
    return {"terms": terms}


@router.put("/terms")
def save_terms(payload: TermsPayload, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Overwrite the entire Terms & Conditions list (preserves order sent by client)."""
        # Sync with new normalized database table
    db.query(models.QuotationTerm).delete()
    for i, term in enumerate(payload.terms):
        db.add(models.QuotationTerm(
            id=str(uuid.uuid4()),
            text=term,
            display_order=i + 1,
            is_enabled=True
        ))
    db.commit()

    # Audit log settings change
    try:
        audit = models.AuditLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            username=current_user.username,
            role=current_user.role,
            action="Settings Changed",
            ip_address="",
            timestamp=int(time.time() * 1000),
            details=f"Updated default terms & conditions ({len(payload.terms)} terms)"
        )
        db.add(audit)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to write settings audit log: {e}")

    return {"terms": payload.terms, "status": "saved"}


# ── Generic key-value settings ──────────────────────────────────────────────

@router.post("/bulk")
def bulk_save_settings(payload: BulkSettingsPayload, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    """Save multiple settings in a single transaction."""
    for key, value in payload.settings.items():
        _upsert_setting(db, key, value)
    db.commit()

    # Audit log bulk settings change
    try:
        audit = models.AuditLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            username=current_user.username,
            role=current_user.role,
            action="Settings Changed",
            ip_address="",
            timestamp=int(time.time() * 1000),
            details=f"Bulk settings update: {', '.join(payload.settings.keys())}"
        )
        db.add(audit)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to write bulk settings audit log: {e}")

    return {"saved": list(payload.settings.keys()), "status": "saved"}


# ─── IMAGE UPLOAD & DELETE ────────────────────────────────────────────────────
# IMPORTANT: These must come BEFORE the generic /{key} catch-all routes!

import schemas

@router.post("/upload")
def upload_image(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(RoleChecker(["admin"]))
):
        # Validate extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"]:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PNG, JPG, JPEG, SVG, WEBP, and GIF are allowed.")
        
    upload_dir = os.path.abspath("uploads")
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(upload_dir, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    logger.info("Uploaded file: %s", filename)
    return {"url": f"/uploads/{filename}", "status": "success"}


@router.delete("/upload/{filename}")
def delete_uploaded_image(
    filename: str,
    current_user: CurrentUser = Depends(RoleChecker(["admin"]))
):
    upload_dir = os.path.abspath("uploads")
    filepath = os.path.join(upload_dir, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        os.remove(filepath)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")
        
    return {"status": "success"}


# ── Generic key-value settings ──────────────────────────────────────────────

@router.get("/{key}")
def get_setting(key: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    row = db.query(models.AppSettings).filter(models.AppSettings.key == key).first()
    return {"key": key, "value": row.value if row else ""}


@router.post("/{key}")
def set_setting(key: str, payload: KVPayload, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    _upsert_setting(db, key, payload.value)
    db.commit()

    # Audit log settings change (skip noisy internal keys)
    noisy_keys = {"sheets_last_sync_time", "sheets_stats_total", "sheets_stats_imported",
                  "sheets_stats_skipped", "sheets_stats_failed", "sheets_sync_status"}
    if key not in noisy_keys:
        try:
            audit = models.AuditLog(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                username=current_user.username,
                role=current_user.role,
                action="Settings Changed",
                ip_address="",
                timestamp=int(time.time() * 1000),
                details=f"Updated setting: {key}"
            )
            db.add(audit)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to write settings audit log: {e}")

    return {"key": key, "value": payload.value, "status": "saved"}


@router.put("/{key}")
def update_setting(key: str, payload: KVPayload, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """PUT alias for POST /settings/{key} — REST compliant update."""
    return set_setting(key, payload, db, current_user)


# ─── DATABASE-DRIVEN CRUD OPERATIONS ─────────────────────────────────────────

# Helper to reduce boilerplate for settings tables CRUD
def make_crud_routes(model, schema_out, schema_create, schema_update, prefix_name):
    # GET list
    @router.get(f"/db/{prefix_name}", response_model=List[schema_out])
    def list_items(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
        return db.query(model).order_by(model.display_order.asc()).all()

    # POST create
    @router.post(f"/db/{prefix_name}", response_model=schema_out, status_code=201)
    def create_item(payload: schema_create, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
        item = model(id=str(uuid.uuid4()), **payload.model_dump())
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    # PUT update
    @router.put(f"/db/{prefix_name}/{{item_id}}", response_model=schema_out)
    def update_item(item_id: str, payload: schema_create, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
        item = db.query(model).filter(model.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        for k, v in payload.model_dump().items():
            setattr(item, k, v)
        db.commit()
        db.refresh(item)
        return item

    # PATCH partial update
    @router.patch(f"/db/{prefix_name}/{{item_id}}", response_model=schema_out)
    def patch_item(item_id: str, payload: schema_update, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
        item = db.query(model).filter(model.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(item, k, v)
        db.commit()
        db.refresh(item)
        return item

    # DELETE
    @router.delete(f"/db/{prefix_name}/{{item_id}}")
    def delete_item(item_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
        item = db.query(model).filter(model.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        db.delete(item)
        db.commit()
        return {"status": "success"}

# Initialize routes for all components
make_crud_routes(models.QuotationTerm, schemas.QuotationTermOut, schemas.QuotationTermCreate, schemas.QuotationTermUpdate, "terms")
make_crud_routes(models.QuotationMaterial, schemas.QuotationMaterialOut, schemas.QuotationMaterialCreate, schemas.QuotationMaterialUpdate, "materials")
make_crud_routes(models.QuotationBank, schemas.QuotationBankOut, schemas.QuotationBankCreate, schemas.QuotationBankUpdate, "banks")
make_crud_routes(models.QuotationSocial, schemas.QuotationSocialOut, schemas.QuotationSocialCreate, schemas.QuotationSocialUpdate, "socials")
make_crud_routes(models.QuotationWhyChoose, schemas.QuotationWhyChooseOut, schemas.QuotationWhyChooseCreate, schemas.QuotationWhyChooseUpdate, "why-chooses")
make_crud_routes(models.QuotationService, schemas.QuotationServiceOut, schemas.QuotationServiceCreate, schemas.QuotationServiceUpdate, "services")
make_crud_routes(models.QuotationFooter, schemas.QuotationFooterOut, schemas.QuotationFooterCreate, schemas.QuotationFooterUpdate, "footers")


