import uuid
import re
import io
import csv
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
import models
import schemas
from auth_utils import get_current_user, RoleChecker, CurrentUser

router = APIRouter(prefix="/products", tags=["Products"])


import json

@router.get("", response_model=List[schemas.ProductOut])
def list_products(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "salesman", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    products = db.query(models.Product).all()
    quotes = db.query(models.Quotation).all()
    name_counts = {}
    for q in quotes:
        try:
            items = json.loads(q.items_json) if q.items_json else []
            for item in items:
                name = item.get("name")
                if name:
                    name_counts[name] = name_counts.get(name, 0) + 1
        except Exception:
            continue
    for p in products:
        p.quote_count = name_counts.get(p.name, 0)
    return products


def validate_product(payload: schemas.ProductCreate, db: Session, product_id: str = None):
    # Name validation
    name_val = payload.name.strip() if payload.name else ""
    if not name_val:
        raise HTTPException(status_code=400, detail="Product name cannot be empty")
    
    # Category validation
    cat_val = payload.category.strip() if payload.category else ""
    if not cat_val:
        raise HTTPException(status_code=400, detail="Product category cannot be empty")
        
    # Unit validation
    unit_val = payload.unit.strip() if payload.unit else ""
    if not unit_val:
        raise HTTPException(status_code=400, detail="Product unit cannot be empty")
        
    # Price validation
    if payload.price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
        
    # HSN code validation
    hsn_val = payload.hsn_code.strip() if payload.hsn_code else ""
    if not hsn_val:
        raise HTTPException(status_code=400, detail="HSN Code is required")
    if not re.match(r"^(\d{4}|\d{6}|\d{8})$", hsn_val):
        raise HTTPException(status_code=400, detail="HSN Code must be 4, 6, or 8 digits and contain only numbers")
        
    # Duplicate name check
    query = db.query(models.Product).filter(func.lower(models.Product.name) == func.lower(name_val))
    if product_id:
        query = query.filter(models.Product.id != product_id)
    if query.first():
        raise HTTPException(status_code=400, detail=f"Product with name '{name_val}' already exists")


@router.post("", response_model=schemas.ProductOut, status_code=201)
def create_product(payload: schemas.ProductCreate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    validate_product(payload, db)
    # Strip fields before saving
    product_data = payload.model_dump()
    product_data['name'] = product_data['name'].strip()
    product_data['category'] = product_data['category'].strip()
    product_data['unit'] = product_data['unit'].strip()
    
    product = models.Product(id=str(uuid.uuid4()), **product_data)
    db.add(product)
    db.commit()
    db.refresh(product)
    
    prod_data = {
        "id": product.id,
        "name": product.name,
        "category": product.category,
        "unit": product.unit,
        "price": product.price,
        "desc": product.desc,
        "hsn_code": product.hsn_code,
        "quote_count": 0
    }
    from websocket_manager import broadcast_event
    broadcast_event("product_created", prod_data)
    
    return product


@router.put("/{product_id}", response_model=schemas.ProductOut)
def update_product(product_id: str, payload: schemas.ProductUpdate, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    validate_product(payload, db, product_id)
    
    product_data = payload.model_dump()
    for field, value in product_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(product, field, value)
        
    db.commit()
    db.refresh(product)
    
    prod_data = {
        "id": product.id,
        "name": product.name,
        "category": product.category,
        "unit": product.unit,
        "price": product.price,
        "desc": product.desc,
        "hsn_code": product.hsn_code,
        "quote_count": 0
    }
    from websocket_manager import broadcast_event
    broadcast_event("product_updated", prod_data)
    
    return product



@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    p_id = product.id
    db.delete(product)
    db.commit()
    
    from websocket_manager import broadcast_event
    broadcast_event("product_deleted", {"id": p_id})


@router.get("/export")
def export_products_csv(db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    products = db.query(models.Product).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(["Name", "Category", "Unit", "Price", "Description", "HSN Code"])
    
    for p in products:
        writer.writerow([p.name, p.category, p.unit, p.price, p.desc or "", p.hsn_code or ""])
        
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_export.csv"}
    )


@router.post("/import")
def import_products_csv(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    if file.content_type and file.content_type not in ["text/csv", "application/vnd.ms-excel", "application/csv", "text/x-csv"]:
        raise HTTPException(status_code=400, detail="Invalid file type. Expected text/csv")
    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 5MB")
        
    try:
        contents = file.file.read().decode("utf-8")
        buffer = io.StringIO(contents)
        reader = csv.reader(buffer)
        
        # Read header
        header = next(reader, None)
        if not header:
            raise HTTPException(status_code=400, detail="CSV file is empty")
            
        # Match columns by header name (case-insensitive)
        header_indices = {col.strip().lower(): idx for idx, col in enumerate(header)}
        
        required_cols = ["name", "category", "unit", "price"]
        for col in required_cols:
            if col not in header_indices:
                raise HTTPException(status_code=400, detail=f"Missing required column: {col}")
                
        name_idx = header_indices["name"]
        category_idx = header_indices["category"]
        unit_idx = header_indices["unit"]
        price_idx = header_indices["price"]
        desc_idx = header_indices.get("description") or header_indices.get("desc")
        hsn_idx = header_indices.get("hsn code") or header_indices.get("hsn_code") or header_indices.get("hsn")
        
        errors = []
        products_to_add = []
        existing_names = {p.name.lower() for p in db.query(models.Product).all()}
        
        for row_num, row in enumerate(reader, start=2):
            if not row or not any(row):  # skip empty rows
                continue
                
            try:
                # Pad row to avoid index errors
                row_padded = row + [""] * (max(header_indices.values()) + 1 - len(row))
                
                name_val = row_padded[name_idx].strip()
                cat_val = row_padded[category_idx].strip()
                unit_val = row_padded[unit_idx].strip()
                price_str = row_padded[price_idx].strip()
                desc_val = row_padded[desc_idx].strip() if desc_idx is not None else ""
                hsn_val = row_padded[hsn_idx].strip() if hsn_idx is not None else ""
                
                if not name_val:
                    errors.append(f"Row {row_num}: Product name cannot be empty")
                    continue
                if name_val.lower() in existing_names:
                    errors.append(f"Row {row_num}: Product name '{name_val}' already exists")
                    continue
                if not cat_val:
                    errors.append(f"Row {row_num}: Product category cannot be empty")
                    continue
                if not unit_val:
                    errors.append(f"Row {row_num}: Product unit cannot be empty")
                    continue
                try:
                    price_val = float(price_str)
                    if price_val < 0:
                        errors.append(f"Row {row_num}: Price cannot be negative")
                        continue
                except ValueError:
                    errors.append(f"Row {row_num}: Invalid price value '{price_str}'")
                    continue
                    
                if not hsn_val:
                    errors.append(f"Row {row_num}: HSN Code is required")
                    continue
                if not re.match(r"^(\d{4}|\d{6}|\d{8})$", hsn_val):
                    errors.append(f"Row {row_num}: HSN Code must be 4, 6, or 8 digits and contain only numbers")
                    continue
                    
                # Add to queue
                p = models.Product(
                    id=str(uuid.uuid4()),
                    name=name_val,
                    category=cat_val,
                    unit=unit_val,
                    price=price_val,
                    desc=desc_val,
                    hsn_code=hsn_val
                )
                products_to_add.append(p)
                existing_names.add(name_val.lower()) # prevent duplicates within the same import
                
            except Exception as e:
                errors.append(f"Row {row_num}: Unexpected error - {str(e)}")
                
        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors[:5]) + (f" (and {len(errors)-5} more errors)" if len(errors) > 5 else ""))
            
        for p in products_to_add:
            db.add(p)
        db.commit()
        return {"status": "success", "imported": len(products_to_add)}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process CSV file: {str(e)}")


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    role_lower = current_user.role.lower()
    if role_lower not in ["admin", "salesman", "telecaller"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    quotes = db.query(models.Quotation).all()
    quote_count = 0
    for q in quotes:
        try:
            items = json.loads(q.items_json) if q.items_json else []
            for item in items:
                if item.get("name") == product.name:
                    quote_count += 1
        except Exception:
            continue
    product.quote_count = quote_count
    return product
