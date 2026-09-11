import uuid
import time
import json
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from database import get_db
import models
import schemas
from auth_utils import get_current_user, CurrentUser, RoleChecker
from websocket_manager import broadcast_event
from routers.inventory import check_and_create_low_stock_pr

router = APIRouter(
    prefix="/factory",
    tags=["Factory Dashboard & Manufacturing ERP"],
    dependencies=[Depends(RoleChecker(["admin", "factory"]))]
)

# Standard 4 Production Statuses for RetailFix Factory Dashboard
PRODUCTION_STAGES = [
    "Accepted",
    "Started",
    "Processing",
    "Completed"
]

DEFAULT_RAW_MATERIALS = [
    {"code": "RM-CRS-001", "name": "CR Sheet", "category": "Sheet Metal", "unit": "Sheet", "default_stock": 200.0, "min": 20.0, "per_item_qty": 2.0},
    {"code": "RM-MSP-001", "name": "MS Pipe", "category": "Pipe & Tube", "unit": "Meter", "default_stock": 500.0, "min": 50.0, "per_item_qty": 4.0},
    {"code": "RM-ANG-001", "name": "Angle", "category": "Pipe & Tube", "unit": "Meter", "default_stock": 300.0, "min": 30.0, "per_item_qty": 3.0},
    {"code": "RM-SHF-001", "name": "Shelf", "category": "Components", "unit": "Pcs", "default_stock": 150.0, "min": 15.0, "per_item_qty": 1.0},
    {"code": "RM-NBT-001", "name": "Nut Bolt", "category": "Hardware", "unit": "Pcs", "default_stock": 5000.0, "min": 500.0, "per_item_qty": 20.0},
    {"code": "RM-PNT-001", "name": "Paint", "category": "Coating & Paint", "unit": "Liter", "default_stock": 100.0, "min": 10.0, "per_item_qty": 0.5},
    {"code": "RM-PWD-001", "name": "Powder", "category": "Coating & Paint", "unit": "Kg", "default_stock": 150.0, "min": 15.0, "per_item_qty": 1.0},
    {"code": "RM-PLV-001", "name": "Plastic Leveler", "category": "Hardware", "unit": "Pcs", "default_stock": 800.0, "min": 80.0, "per_item_qty": 4.0},
    {"code": "RM-ACC-001", "name": "Accessories", "category": "Accessories", "unit": "Set", "default_stock": 100.0, "min": 10.0, "per_item_qty": 1.0},
]


def ensure_default_raw_materials(db: Session):
    """Ensure standard raw materials exist in database for automatic requirement calculation."""
    now = int(time.time() * 1000)
    for mdef in DEFAULT_RAW_MATERIALS:
        mat = db.query(models.RawMaterial).filter(models.RawMaterial.material_code == mdef["code"]).first()
        if not mat:
            mat = models.RawMaterial(
                id=str(uuid.uuid4()),
                material_code=mdef["code"],
                name=mdef["name"],
                category=mdef["category"],
                unit=mdef["unit"],
                current_stock=mdef["default_stock"],
                reserved_stock=0.0,
                minimum_level=mdef["min"],
                reorder_quantity=mdef["min"] * 3,
                unit_cost=100.0,
                location="Main Factory Warehouse",
                created_at=now,
                updated_at=now
            )
            db.add(mat)
    db.flush()


def generate_production_order_from_quotation(db: Session, quotation_id: str) -> tuple[Optional[models.ProductionOrder], bool]:
    """Automatically generate a Production Order from an approved/paid quotation.
    Auto-reserves raw materials, initializes stages.
    """
    # Verify quotation exists
    q = db.query(models.Quotation).filter(models.Quotation.id == quotation_id).first()
    if not q:
        return None, False

    # Check if a production order already exists for this quotation
    existing = db.query(models.ProductionOrder).filter(models.ProductionOrder.quotation_id == quotation_id).first()
    if existing:
        # Update payment status if needed
        existing.payment_status = q.payment_status or "Paid"
        db.flush()
        return existing, False

    ensure_default_raw_materials(db)

    now_ms = int(time.time() * 1000)
    year_str = time.strftime("%Y")
    po_count = db.query(models.ProductionOrder).count() + 1
    po_number = f"RF-PO-{year_str}-{po_count:05d}"

    # Calculate expected dispatch date (7 days from creation default)
    dispatch_dt = datetime.datetime.now() + datetime.timedelta(days=7)
    dispatch_date_str = dispatch_dt.strftime("%Y-%m-%d")

    # Fetch salesman name if lead exists
    salesman_name = "Direct Sales"
    if q.customer_phone:
        lead = db.query(models.Lead).filter(models.Lead.phone == q.customer_phone).first()
        if lead and lead.salesman_name:
            salesman_name = lead.salesman_name

    po = models.ProductionOrder(
        id=str(uuid.uuid4()),
        production_number=po_number,
        quotation_id=q.id,
        quote_number=q.quote_number,
        customer_id=q.customer_id or "",
        customer_name=q.customer_name,
        mobile=q.customer_phone or "",
        address=q.customer_address or f"{q.customer_city}".strip(),
        payment_status=q.payment_status or "Paid",
        priority="Medium",
        order_date=now_ms,
        expected_dispatch=dispatch_date_str,
        sales_person=salesman_name,
        status="Accepted",
        current_stage="Accepted",
        customer_notes=f"City: {q.customer_city}, GST: {q.customer_gstin}".strip(),
        quotation_remarks=f"Payment Mode: {q.payment_type}, Grand Total: ₹{q.grand_total:,.2f}",
        sales_instructions="Auto-generated on payment receipt. Quality check and proper packaging required before dispatch.",
        created_at=now_ms,
        updated_at=now_ms
    )
    db.add(po)
    db.flush()

    # Copy items from quotation items_json
    raw_items = []
    try:
        raw_items = json.loads(q.items_json) if q.items_json else []
    except Exception:
        raw_items = []

    total_item_qty = 0.0
    for item in raw_items:
        qty = float(item.get("qty", item.get("quantity", 1)))
        total_item_qty += qty
        desc = item.get("description") or item.get("desc") or item.get("remarks") or f"Category: {item.get('category', 'Standard')}"
        p_item = models.ProductionItem(
            id=str(uuid.uuid4()),
            production_order_id=po.id,
            product_id="",
            product_name=item.get("name", "Custom Item"),
            product_description=desc,
            hsn=item.get("hsn_code", "7308"),
            quantity=qty,
            unit=item.get("unit", "Pcs"),
            product_image=item.get("image", item.get("product_image", "")),
            remarks=item.get("remarks", "")
        )
        db.add(p_item)

    # Initialize default 4 production status history records
    for idx, stage_name in enumerate(PRODUCTION_STAGES):
        st_status = "Completed" if stage_name == "Accepted" else "Pending"
        st_start = now_ms if stage_name == "Accepted" else 0
        st_end = now_ms if stage_name == "Accepted" else 0
        stage_record = models.ProductionStatusHistory(
            id=str(uuid.uuid4()),
            production_order_id=po.id,
            stage_name=stage_name,
            status=st_status,
            start_time=st_start,
            end_time=st_end,
            completed_by="System" if stage_name == "Accepted" else "",
            remarks="Order auto-created upon payment receipt" if stage_name == "Accepted" else "",
            created_at=now_ms
        )
        db.add(stage_record)

    # Auto calculate free-text manufacturing materials
    materials_needed = {} # normalized_description: { "desc": ..., "qty": ..., "unit": ... }
    
    for item in raw_items:
        qty = float(item.get("qty", item.get("quantity", 1)))
        prod_name = item.get("name", "")
        if not prod_name:
            continue
            
        product = db.query(models.Product).filter(models.Product.name == prod_name).first()
        if product and product.manufacturing_materials_json:
            try:
                mats = json.loads(product.manufacturing_materials_json)
                for mat in mats:
                    desc = str(mat.get("description", "")).strip()
                    if not desc:
                        continue
                    mat_qty = float(mat.get("qty", mat.get("quantity", 0))) * qty
                    mat_unit = mat.get("unit", "")
                    
                    norm_desc = desc.lower()
                    if norm_desc in materials_needed:
                        materials_needed[norm_desc]["qty"] += mat_qty
                    else:
                        materials_needed[norm_desc] = {
                            "desc": desc,
                            "qty": mat_qty,
                            "unit": mat_unit
                        }
            except Exception as e:
                pass

    for norm_desc, mat_data in materials_needed.items():
        m_req = models.ProductionMaterialRequirement(
            id=str(uuid.uuid4()),
            production_order_id=po.id,
            material_id="",
            material_name=mat_data["desc"],
            material_description=mat_data["desc"],
            required_qty=mat_data["qty"],
            reserved_qty=0.0,
            deducted_qty=0.0,
            unit=mat_data["unit"] or "Pcs",
            status="Reserved",
            created_at=now_ms
        )
        db.add(m_req)

    # Add default quotation attachment reference
    att = models.ProductionAttachment(
        id=str(uuid.uuid4()),
        production_order_id=po.id,
        file_name=f"Quotation_{q.quote_number}.pdf",
        file_type="Quotation PDF",
        file_url=f"/api/quotations/{q.id}/pdf",
        uploaded_at=now_ms
    )
    db.add(att)

    # Create real-time notification for Factory Manager
    from models import create_notification
    create_notification(
        db,
        message=f"🔴 NEW ORDER: Production Order {po.production_number} generated for {po.customer_name} ({po.quote_number})",
        type="New Production Order",
        role="admin"
    )

    db.flush()

    db.flush()
    return po, True


@router.get("/kpis", response_model=schemas.ProductionDashboardKPIs)
def get_factory_dashboard_kpis(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    now = datetime.datetime.now()
    today_start = int(datetime.datetime(now.year, now.month, now.day, 0, 0, 0).timestamp() * 1000)

    total_orders = db.query(models.ProductionOrder).count()
    accepted = db.query(models.ProductionOrder).filter(models.ProductionOrder.status == "Accepted").count()
    started = db.query(models.ProductionOrder).filter(models.ProductionOrder.status == "Started").count()
    processing = db.query(models.ProductionOrder).filter(models.ProductionOrder.status == "Processing").count()
    completed = db.query(models.ProductionOrder).filter(models.ProductionOrder.status == "Completed").count()
    today_orders = db.query(models.ProductionOrder).filter(models.ProductionOrder.created_at >= today_start).count()

    today_str = now.strftime("%Y-%m-%d")
    late_orders = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.status != "Completed",
        models.ProductionOrder.expected_dispatch != "",
        models.ProductionOrder.expected_dispatch < today_str
    ).count()

    return schemas.ProductionDashboardKPIs(
        total_orders=total_orders,
        accepted=accepted,
        started=started,
        processing=processing,
        completed=completed,
        accepted_orders=accepted,
        started_orders=started,
        processing_orders=processing,
        completed_orders=completed,
        today_orders=today_orders,
        late_orders=late_orders
    )


@router.get("/orders", response_model=List[schemas.ProductionOrderOut])
def list_production_orders(
    status: Optional[str] = None,
    stage: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    today_only: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    query = db.query(models.ProductionOrder)

    if today_only:
        now = datetime.datetime.now()
        today_start = int(datetime.datetime(now.year, now.month, now.day, 0, 0, 0).timestamp() * 1000)
        query = query.filter(models.ProductionOrder.created_at >= today_start)

    if status and status != "All":
        query = query.filter(models.ProductionOrder.status == status)

    if stage and stage != "All":
        query = query.filter(models.ProductionOrder.current_stage == stage)

    if priority and priority != "All":
        query = query.filter(models.ProductionOrder.priority == priority)

    if search:
        s = f"%{search}%"
        query = query.filter(or_(
            models.ProductionOrder.production_number.ilike(s),
            models.ProductionOrder.quote_number.ilike(s),
            models.ProductionOrder.customer_name.ilike(s),
            models.ProductionOrder.mobile.ilike(s)
        ))

    orders = query.order_by(models.ProductionOrder.created_at.desc()).all()

    result = []
    for po in orders:
        po_out = build_production_order_out(db, po)
        result.append(po_out)
    return result


def build_production_order_out(db: Session, po: models.ProductionOrder) -> schemas.ProductionOrderOut:
    items = db.query(models.ProductionItem).filter(models.ProductionItem.production_order_id == po.id).all()
    workers = db.query(models.ProductionWorker).filter(models.ProductionWorker.production_order_id == po.id).all()
    stages = db.query(models.ProductionStatusHistory).filter(models.ProductionStatusHistory.production_order_id == po.id).order_by(models.ProductionStatusHistory.created_at.asc()).all()
    notes = db.query(models.ProductionNote).filter(models.ProductionNote.production_order_id == po.id).order_by(models.ProductionNote.created_at.desc()).all()
    atts = db.query(models.ProductionAttachment).filter(models.ProductionAttachment.production_order_id == po.id).all()
    reqs = db.query(models.ProductionMaterialRequirement).filter(models.ProductionMaterialRequirement.production_order_id == po.id).all()

    out = schemas.ProductionOrderOut.model_validate(po)
    out.items = [schemas.ProductionItemOut.model_validate(i) for i in items]
    out.workers = [schemas.ProductionWorkerOut.model_validate(w) for w in workers]
    out.stages = [schemas.ProductionStatusHistoryOut.model_validate(s) for s in stages]
    out.notes = [schemas.ProductionNoteOut.model_validate(n) for n in notes]
    out.attachments = [schemas.ProductionAttachmentOut.model_validate(a) for a in atts]
    out.material_requirements = [schemas.ProductionMaterialRequirementOut.model_validate(r) for r in reqs]
    return out


@router.get("/orders/{order_id}", response_model=schemas.ProductionOrderOut)
def get_production_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")
    return build_production_order_out(db, po)


@router.post("/orders/{order_id}/status", response_model=schemas.ProductionOrderOut)
def update_order_status(
    order_id: str,
    status: str = Query(..., description="Target status: Accepted | Started | Processing | Completed"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    valid_statuses = ["Accepted", "Started", "Processing", "Completed"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of {valid_statuses}")

    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    now = int(time.time() * 1000)
    po.status = status
    po.current_stage = status
    po.updated_at = now

    st = db.query(models.ProductionStatusHistory).filter(
        models.ProductionStatusHistory.production_order_id == po.id,
        models.ProductionStatusHistory.stage_name == status
    ).first()
    if not st:
        st = models.ProductionStatusHistory(
            id=str(uuid.uuid4()),
            production_order_id=po.id,
            stage_name=status,
            created_at=now
        )
        db.add(st)
    
    st.status = "Completed"
    if not st.start_time:
        st.start_time = now
    st.end_time = now
    st.completed_by = current_user.username or "Factory Staff"
    st.remarks = f"Status updated to {status}"

    db.commit()
    broadcast_event("production_order_updated", {
        "id": po.id,
        "production_number": po.production_number,
        "status": po.status,
        "current_stage": po.current_stage
    })
    return build_production_order_out(db, po)


@router.post("/orders/{order_id}/accept", response_model=schemas.ProductionOrderOut)
def accept_production_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    now = int(time.time() * 1000)
    po.status = "Accepted"
    po.current_stage = "Accepted"
    po.updated_at = now

    # Update stage history
    st = db.query(models.ProductionStatusHistory).filter(
        models.ProductionStatusHistory.production_order_id == po.id,
        models.ProductionStatusHistory.stage_name == "Accepted"
    ).first()
    if st:
        st.status = "Completed"
        st.start_time = now
        st.end_time = now
        st.completed_by = current_user.username
        st.remarks = "Accepted by Factory Manager"

    db.commit()
    broadcast_event("production_order_updated", {"id": po.id, "status": po.status, "stage": po.current_stage})
    return build_production_order_out(db, po)


@router.post("/orders/{order_id}/reject", response_model=schemas.ProductionOrderOut)
def reject_production_order(
    order_id: str,
    reason: str = Query(..., description="Reason for rejection"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    now = int(time.time() * 1000)
    po.status = "Rejected"
    po.updated_at = now

    note = models.ProductionNote(
        id=str(uuid.uuid4()),
        production_order_id=po.id,
        author=current_user.username,
        note=f"🔴 ORDER REJECTED: {reason}",
        created_at=now
    )
    db.add(note)

    # Release any reserved stock back to raw materials
    reqs = db.query(models.ProductionMaterialRequirement).filter(models.ProductionMaterialRequirement.production_order_id == po.id).all()
    for r in reqs:
        if r.reserved_qty > 0:
            mat = db.query(models.RawMaterial).filter(models.RawMaterial.id == r.material_id).first()
            if mat:
                mat.reserved_stock = max(0.0, mat.reserved_stock - r.reserved_qty)
                tx = models.InventoryTransaction(
                    id=str(uuid.uuid4()),
                    material_id=mat.id,
                    material_name=mat.name,
                    type="Released",
                    qty=r.reserved_qty,
                    reference_id=po.production_number,
                    remarks=f"Stock released due to rejection of {po.production_number}",
                    created_by=current_user.username,
                    created_at=now
                )
                db.add(tx)
            r.reserved_qty = 0.0
            r.status = "Released"

    db.commit()
    broadcast_event("production_order_updated", {"id": po.id, "status": po.status})
    return build_production_order_out(db, po)


@router.post("/orders/{order_id}/assign-workers", response_model=schemas.ProductionOrderOut)
def assign_workers(
    order_id: str,
    workers: List[schemas.ProductionWorkerCreate],
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    # Clear previous assigned workers and add new
    db.query(models.ProductionWorker).filter(models.ProductionWorker.production_order_id == po.id).delete()

    now = int(time.time() * 1000)
    for w in workers:
        wk = models.ProductionWorker(
            id=str(uuid.uuid4()),
            production_order_id=po.id,
            worker_name=w.worker_name,
            role=w.role,
            assigned_at=now,
            assigned_by=current_user.username
        )
        db.add(wk)

    po.updated_at = now
    db.commit()
    broadcast_event("production_order_updated", {"id": po.id})
    return build_production_order_out(db, po)


@router.post("/orders/{order_id}/stages/action", response_model=schemas.ProductionOrderOut)
def update_stage_action(
    order_id: str,
    payload: schemas.ProductionStageAction,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    stage_record = db.query(models.ProductionStatusHistory).filter(
        models.ProductionStatusHistory.production_order_id == po.id,
        models.ProductionStatusHistory.stage_name == payload.stage_name
    ).first()

    if not stage_record:
        # Create stage record if not present
        stage_record = models.ProductionStatusHistory(
            id=str(uuid.uuid4()),
            production_order_id=po.id,
            stage_name=payload.stage_name,
            status="Pending",
            created_at=int(time.time() * 1000)
        )
        db.add(stage_record)

    now = int(time.time() * 1000)
    act = payload.action.lower()

    if act == "start":
        stage_record.status = "In Progress"
        stage_record.start_time = now
        stage_record.completed_by = payload.completed_by or current_user.username
        if payload.remarks: stage_record.remarks = payload.remarks
        po.current_stage = payload.stage_name
        po.status = "In Production"

        # If Material Issued stage starts or production starts: deduct reserved raw materials
        if payload.stage_name in ["Material Issued", "Cutting"]:
            reqs = db.query(models.ProductionMaterialRequirement).filter(
                models.ProductionMaterialRequirement.production_order_id == po.id,
                models.ProductionMaterialRequirement.status != "Issued"
            ).all()
            for r in reqs:
                mat = db.query(models.RawMaterial).filter(models.RawMaterial.id == r.material_id).first()
                if mat and r.reserved_qty > 0:
                    mat.current_stock = max(0.0, mat.current_stock - r.reserved_qty)
                    mat.reserved_stock = max(0.0, mat.reserved_stock - r.reserved_qty)
                    mat.updated_at = now
                    r.deducted_qty += r.reserved_qty
                    r.reserved_qty = 0.0
                    r.status = "Issued"

                    tx = models.InventoryTransaction(
                        id=str(uuid.uuid4()),
                        material_id=mat.id,
                        material_name=mat.name,
                        type="Deducted",
                        qty=r.deducted_qty,
                        reference_id=po.production_number,
                        remarks=f"Materials issued for Production Order {po.production_number}",
                        created_by=current_user.username,
                        created_at=now
                    )
                    db.add(tx)
                    check_and_create_low_stock_pr(db, mat, f"Stock deducted for PO {po.production_number}")

    elif act == "pause":
        stage_record.status = "Paused"
        if payload.remarks: stage_record.remarks = payload.remarks

    elif act == "resume":
        stage_record.status = "In Progress"

    elif act == "complete":
        stage_record.status = "Completed"
        stage_record.end_time = now
        if not stage_record.start_time: stage_record.start_time = now
        stage_record.completed_by = payload.completed_by or current_user.username
        if payload.remarks: stage_record.remarks = payload.remarks

        # Update high-level PO status based on stage
        if payload.stage_name == "Quality Check":
            po.status = "Quality Check"
            po.current_stage = "Quality Check"
        elif payload.stage_name == "Packing":
            po.status = "Packing"
            po.current_stage = "Packing"
        elif payload.stage_name == "Ready for Dispatch":
            po.status = "Ready for Dispatch"
            po.current_stage = "Ready for Dispatch"
        elif payload.stage_name == "Completed":
            po.status = "Completed"
            po.current_stage = "Completed"
        else:
            # Advance to next stage in workflow automatically
            curr_idx = PRODUCTION_STAGES.index(payload.stage_name) if payload.stage_name in PRODUCTION_STAGES else -1
            if curr_idx != -1 and curr_idx + 1 < len(PRODUCTION_STAGES):
                next_stage = PRODUCTION_STAGES[curr_idx + 1]
                po.current_stage = next_stage

    elif act == "skip":
        stage_record.status = "Skipped"

    po.updated_at = now
    db.commit()
    broadcast_event("production_order_updated", {"id": po.id, "status": po.status, "stage": po.current_stage})
    return build_production_order_out(db, po)


@router.put("/orders/{order_id}/priority", response_model=schemas.ProductionOrderOut)
def update_order_priority(
    order_id: str,
    payload: schemas.ProductionOrderPriorityUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    po.priority = payload.priority
    po.updated_at = int(time.time() * 1000)
    db.commit()
    broadcast_event("production_order_updated", {"id": po.id, "priority": po.priority})
    return build_production_order_out(db, po)


@router.post("/orders/{order_id}/notes", response_model=schemas.ProductionOrderOut)
def add_production_note(
    order_id: str,
    payload: schemas.ProductionNoteCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    now = int(time.time() * 1000)
    note = models.ProductionNote(
        id=str(uuid.uuid4()),
        production_order_id=po.id,
        author=payload.author or current_user.username,
        note=payload.note,
        created_at=now
    )
    db.add(note)
    po.updated_at = now
    db.commit()
    return build_production_order_out(db, po)


@router.post("/orders/{order_id}/attachments", response_model=schemas.ProductionOrderOut)
def add_production_attachment(
    order_id: str,
    payload: schemas.ProductionAttachmentCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    now = int(time.time() * 1000)
    att = models.ProductionAttachment(
        id=str(uuid.uuid4()),
        production_order_id=po.id,
        file_name=payload.file_name,
        file_type=payload.file_type or "General",
        file_url=payload.file_url,
        uploaded_at=now
    )
    db.add(att)
    po.updated_at = now
    db.commit()
    return build_production_order_out(db, po)



@router.post("/orders/{order_id}/materials/{material_id}/progress", response_model=schemas.ProductionMaterialRequirementOut)
def update_material_progress(
    order_id: str,
    material_id: str,
    payload: schemas.MaterialProgressUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Factory worker records manufacturing progress for a specific material.
    - prepared_qty must be between 0 and required_qty.
    - manufacturing_status is determined by the backend (never trusted from frontend).
    - Inventory fields (reserved_qty, deducted_qty, status) remain UNTOUCHED.
    """
    # Verify production order exists
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    # Verify the material requirement belongs to this order
    req = db.query(models.ProductionMaterialRequirement).filter(
        models.ProductionMaterialRequirement.id == material_id,
        models.ProductionMaterialRequirement.production_order_id == order_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Material requirement not found for this order")

    prepared = payload.prepared_qty

    # Validate: cannot exceed required_qty
    if prepared > req.required_qty:
        raise HTTPException(
            status_code=400,
            detail=f"prepared_qty ({prepared}) cannot exceed required_qty ({req.required_qty})"
        )

    # Apply update
    req.prepared_qty = prepared

    # Determine manufacturing_status from backend — never trust frontend
    if prepared == 0:
        req.manufacturing_status = "Pending"
    elif prepared < req.required_qty:
        req.manufacturing_status = "In Progress"
    else:
        req.manufacturing_status = "Completed"

    po.updated_at = int(time.time() * 1000)
    db.commit()
    db.refresh(req)

    # Broadcast update — WebSocket failure must not block DB commit
    try:
        broadcast_event("material_progress_updated", {
            "production_order_id": order_id,
            "production_number": po.production_number,
            "material_id": material_id,
            "material_name": req.material_name,
            "required_qty": req.required_qty,
            "prepared_qty": req.prepared_qty,
            "manufacturing_status": req.manufacturing_status
        })
    except Exception:
        pass  # WebSocket is for notification only; DB update already committed

    return schemas.ProductionMaterialRequirementOut.model_validate(req)


@router.post("/orders/{order_id}/complete_production", response_model=schemas.ProductionOrderOut)
def complete_production_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Mark a production order as Completed.
    Backend enforces that ALL material requirements must have manufacturing_status == 'Completed'.
    If any material is not completed, the request is rejected with a business error.
    """
    po = db.query(models.ProductionOrder).filter(models.ProductionOrder.id == order_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="Production order not found")

    if po.status == "Completed":
        raise HTTPException(status_code=400, detail="Production order is already completed")

    # Fetch ALL material requirements for this order
    reqs = db.query(models.ProductionMaterialRequirement).filter(
        models.ProductionMaterialRequirement.production_order_id == order_id
    ).all()

    # Backend enforces: every material must be completed
    if reqs:
        incomplete = [
            r.material_name for r in reqs
            if r.manufacturing_status != "Completed"
        ]
        if incomplete:
            raise HTTPException(
                status_code=400,
                detail=f"All material requirements must be completed before completing this order. "
                       f"Incomplete: {', '.join(incomplete[:5])}"
                       + (f" (and {len(incomplete) - 5} more)" if len(incomplete) > 5 else "")
            )

    now = int(time.time() * 1000)
    po.status = "Completed"
    po.current_stage = "Completed"
    po.updated_at = now

    # Update stage history record
    st = db.query(models.ProductionStatusHistory).filter(
        models.ProductionStatusHistory.production_order_id == po.id,
        models.ProductionStatusHistory.stage_name == "Completed"
    ).first()
    if not st:
        st = models.ProductionStatusHistory(
            id=str(uuid.uuid4()),
            production_order_id=po.id,
            stage_name="Completed",
            status="Completed",
            created_at=now
        )
        db.add(st)
    st.status = "Completed"
    if not st.start_time:
        st.start_time = now
    st.end_time = now
    st.completed_by = current_user.username or "Factory Staff"
    st.remarks = "All materials completed. Production order marked as Complete — Ready to Dispatch."

    db.commit()

    try:
        broadcast_event("production_order_updated", {
            "id": po.id,
            "production_number": po.production_number,
            "status": po.status,
            "current_stage": po.current_stage
        })
    except Exception:
        pass

    return build_production_order_out(db, po)


@router.get("/reports")
def get_production_reports(
    report_type: str = Query("daily", description="daily | weekly | monthly | worker_performance | pending | completed"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    now = datetime.datetime.now()
    
    if report_type == "daily":
        today_start = int(datetime.datetime(now.year, now.month, now.day, 0, 0, 0).timestamp() * 1000)
        created = db.query(models.ProductionOrder).filter(models.ProductionOrder.created_at >= today_start).all()
        completed = db.query(models.ProductionOrder).filter(models.ProductionOrder.status == "Completed", models.ProductionOrder.updated_at >= today_start).all()
        return {
            "report_type": "Daily Production Summary",
            "date": now.strftime("%Y-%m-%d"),
            "total_new_orders": len(created),
            "total_completed_orders": len(completed),
            "orders": [build_production_order_out(db, o) for o in created]
        }

    elif report_type == "worker_performance":
        workers = db.query(models.ProductionWorker).all()
        stats = {}
        for w in workers:
            if w.worker_name not in stats:
                stats[w.worker_name] = {"name": w.worker_name, "role": w.role, "assignments": 0}
            stats[w.worker_name]["assignments"] += 1
        return {"report_type": "Worker Performance Summary", "workers": list(stats.values())}

    elif report_type in ["pending", "completed"]:
        st = "Pending" if report_type == "pending" else "Completed"
        orders = db.query(models.ProductionOrder).filter(models.ProductionOrder.status == st).all()
        return {
            "report_type": f"{st} Production Orders Report",
            "count": len(orders),
            "orders": [build_production_order_out(db, o) for o in orders]
        }

    else:
        # Default weekly/monthly summary
        days = 7 if report_type == "weekly" else 30
        since = int((now - datetime.timedelta(days=days)).timestamp() * 1000)
        orders = db.query(models.ProductionOrder).filter(models.ProductionOrder.created_at >= since).all()
        return {
            "report_type": f"{report_type.capitalize()} Production Report",
            "timeframe_days": days,
            "total_orders": len(orders),
            "orders": [build_production_order_out(db, o) for o in orders]
        }

