import uuid
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
import models
import schemas
from auth_utils import get_current_user, CurrentUser
from websocket_manager import broadcast_event

router = APIRouter(prefix="/inventory", tags=["Inventory & Raw Materials"])


def check_and_create_low_stock_pr(db: Session, material: models.RawMaterial, reason: str = ""):
    """Helper to check if material stock is below minimum level and auto-generate Purchase Request."""
    available = max(0.0, material.current_stock - material.reserved_stock)
    if available <= material.minimum_level:
        # Check if an active/pending PR already exists for this material
        existing_pr = db.query(models.PurchaseRequest).filter(
            models.PurchaseRequest.material_id == material.id,
            models.PurchaseRequest.status.in_(["Pending", "Approved", "Ordered"])
        ).first()

        if not existing_pr:
            year_str = time.strftime("%Y")
            count = db.query(models.PurchaseRequest).count() + 1
            pr_num = f"PR-{year_str}-{count:05d}"
            
            reorder_qty = max(material.reorder_quantity, material.minimum_level * 2)
            pr = models.PurchaseRequest(
                id=str(uuid.uuid4()),
                request_number=pr_num,
                material_id=material.id,
                material_name=material.name,
                requested_qty=reorder_qty,
                unit=material.unit,
                status="Pending",
                reason=reason or f"Automatic reorder: Available stock ({available} {material.unit}) reached minimum level ({material.minimum_level} {material.unit})",
                created_by="System (Auto Reorder)",
                created_at=int(time.time() * 1000)
            )
            db.add(pr)
            db.flush()

            # Create notification
            from models import create_notification
            create_notification(
                db,
                message=f"⚠️ Low Stock Alert: {material.name} stock ({available} {material.unit}) reached minimum level. Auto-generated Purchase Request {pr_num}.",
                type="Low Stock Alert",
                role="admin"
            )
            broadcast_event("purchase_request_created", {
                "id": pr.id,
                "request_number": pr.request_number,
                "material_name": pr.material_name,
                "requested_qty": pr.requested_qty
            })
            return pr
    return None


@router.get("/materials", response_model=List[schemas.RawMaterialOut])
def list_raw_materials(
    search: Optional[str] = None,
    category: Optional[str] = None,
    low_stock_only: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    query = db.query(models.RawMaterial)
    if search:
        s = f"%{search}%"
        query = query.filter(or_(
            models.RawMaterial.name.ilike(s),
            models.RawMaterial.material_code.ilike(s),
            models.RawMaterial.category.ilike(s)
        ))
    if category and category != "All":
        query = query.filter(models.RawMaterial.category == category)
        
    materials = query.order_by(models.RawMaterial.name.asc()).all()
    
    result = []
    for m in materials:
        avail = max(0.0, m.current_stock - m.reserved_stock)
        is_low = avail <= m.minimum_level
        if low_stock_only and not is_low:
            continue
        out = schemas.RawMaterialOut.model_validate(m)
        out.available_stock = avail
        out.is_low_stock = is_low
        result.append(out)
    return result


@router.post("/materials", response_model=schemas.RawMaterialOut, status_code=201)
def create_raw_material(
    payload: schemas.RawMaterialCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    existing = db.query(models.RawMaterial).filter(models.RawMaterial.material_code == payload.material_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Material code already exists")

    now = int(time.time() * 1000)
    mat = models.RawMaterial(
        id=str(uuid.uuid4()),
        material_code=payload.material_code,
        name=payload.name,
        category=payload.category or "General",
        unit=payload.unit or "Pcs",
        current_stock=payload.current_stock,
        reserved_stock=payload.reserved_stock,
        minimum_level=payload.minimum_level,
        reorder_quantity=payload.reorder_quantity,
        unit_cost=payload.unit_cost,
        location=payload.location or "Main Factory Warehouse",
        created_at=now,
        updated_at=now
    )
    db.add(mat)
    db.commit()
    db.refresh(mat)

    # Initial stock transaction log
    if mat.current_stock > 0:
        tx = models.InventoryTransaction(
            id=str(uuid.uuid4()),
            material_id=mat.id,
            material_name=mat.name,
            type="Stock In",
            qty=mat.current_stock,
            remarks="Initial stock setup",
            created_by=current_user.username,
            created_at=now
        )
        db.add(tx)
        db.commit()

    check_and_create_low_stock_pr(db, mat, "Initial material creation low stock check")
    db.commit()

    out = schemas.RawMaterialOut.model_validate(mat)
    out.available_stock = max(0.0, mat.current_stock - mat.reserved_stock)
    out.is_low_stock = out.available_stock <= mat.minimum_level
    broadcast_event("raw_material_updated", {"id": mat.id, "name": mat.name})
    return out


@router.put("/materials/{material_id}", response_model=schemas.RawMaterialOut)
def update_raw_material(
    material_id: str,
    payload: schemas.RawMaterialUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    mat = db.query(models.RawMaterial).filter(models.RawMaterial.id == material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="Raw material not found")

    old_stock = mat.current_stock
    now = int(time.time() * 1000)

    if payload.name is not None: mat.name = payload.name
    if payload.category is not None: mat.category = payload.category
    if payload.unit is not None: mat.unit = payload.unit
    if payload.minimum_level is not None: mat.minimum_level = payload.minimum_level
    if payload.reorder_quantity is not None: mat.reorder_quantity = payload.reorder_quantity
    if payload.unit_cost is not None: mat.unit_cost = payload.unit_cost
    if payload.location is not None: mat.location = payload.location

    if payload.current_stock is not None and payload.current_stock != old_stock:
        diff = payload.current_stock - old_stock
        mat.current_stock = payload.current_stock
        tx_type = "Stock In" if diff > 0 else "Adjustment"
        tx = models.InventoryTransaction(
            id=str(uuid.uuid4()),
            material_id=mat.id,
            material_name=mat.name,
            type=tx_type,
            qty=diff,
            remarks=f"Stock updated manually by {current_user.username}",
            created_by=current_user.username,
            created_at=now
        )
        db.add(tx)

    mat.updated_at = now
    db.commit()
    db.refresh(mat)

    check_and_create_low_stock_pr(db, mat, "Stock update low stock check")
    db.commit()

    out = schemas.RawMaterialOut.model_validate(mat)
    out.available_stock = max(0.0, mat.current_stock - mat.reserved_stock)
    out.is_low_stock = out.available_stock <= mat.minimum_level
    broadcast_event("raw_material_updated", {"id": mat.id, "name": mat.name})
    return out


@router.get("/transactions", response_model=List[schemas.InventoryTransactionOut])
def list_inventory_transactions(
    material_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    query = db.query(models.InventoryTransaction)
    if material_id:
        query = query.filter(models.InventoryTransaction.material_id == material_id)
    return query.order_by(models.InventoryTransaction.created_at.desc()).limit(limit).all()


@router.get("/purchase-requests", response_model=List[schemas.PurchaseRequestOut])
def list_purchase_requests(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    query = db.query(models.PurchaseRequest)
    if status and status != "All":
        query = query.filter(models.PurchaseRequest.status == status)
    return query.order_by(models.PurchaseRequest.created_at.desc()).all()


@router.patch("/purchase-requests/{pr_id}/status", response_model=schemas.PurchaseRequestOut)
def update_purchase_request_status(
    pr_id: str,
    status: str = Query(..., description="Status: Approved | Ordered | Fulfilled | Cancelled"),
    received_qty: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    pr = db.query(models.PurchaseRequest).filter(models.PurchaseRequest.id == pr_id).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Purchase Request not found")

    old_status = pr.status
    pr.status = status

    # If PR is fulfilled, automatically add stock to RawMaterial!
    if status == "Fulfilled" and old_status != "Fulfilled":
        mat = db.query(models.RawMaterial).filter(models.RawMaterial.id == pr.material_id).first()
        if mat:
            add_qty = received_qty if (received_qty is not None and received_qty > 0) else pr.requested_qty
            mat.current_stock += add_qty
            mat.updated_at = int(time.time() * 1000)

            tx = models.InventoryTransaction(
                id=str(uuid.uuid4()),
                material_id=mat.id,
                material_name=mat.name,
                type="Stock In",
                qty=add_qty,
                reference_id=pr.request_number,
                remarks=f"Purchase Request {pr.request_number} fulfilled",
                created_by=current_user.username,
                created_at=int(time.time() * 1000)
            )
            db.add(tx)

    db.commit()
    db.refresh(pr)
    broadcast_event("purchase_request_updated", {"id": pr.id, "status": pr.status})
    return pr
