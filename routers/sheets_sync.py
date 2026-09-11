import json
import logging
import time
import urllib.request
import re
import csv
import io
import uuid
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
import models
import schemas
from auth_utils import get_current_user, RoleChecker, CurrentUser

router = APIRouter(prefix="/sheets-sync", tags=["Google Sheets Sync"])
logger = logging.getLogger(__name__)


def get_setting(db: Session, key: str) -> str:
    row = db.query(models.AppSettings).filter(models.AppSettings.key == key).first()
    return row.value.strip() if row and row.value else ""


def set_setting(db: Session, key: str, value: str):
    row = db.query(models.AppSettings).filter(models.AppSettings.key == key).first()
    if row is None:
        row = models.AppSettings(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.flush()


def extract_spreadsheet_id(url: str) -> str:
    # Match long string between /d/ and next slash or edit
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return match.group(1) if match else ""


def get_csv_export_url(url: str) -> str:
    spreadsheet_id = extract_spreadsheet_id(url)
    if not spreadsheet_id:
        return ""
    export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv"
    # Capture gid if specified
    gid_match = re.search(r"[#&?]gid=([0-9]+)", url)
    if gid_match:
        export_url += f"&gid={gid_match.group(1)}"
    return export_url


def fetch_csv_content(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8")


def parse_csv_leads(csv_text: str) -> list[dict]:
    f = io.StringIO(csv_text)
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return []
    
    headers = [h.strip().lower() for h in rows[0]]
    leads_data = []
    
    # Flexible header indexes
    phone_idx = -1
    name_idx = -1
    email_idx = -1
    city_idx = -1
    shop_idx = -1
    biz_idx = -1
    address_idx = -1
    
    for idx, h in enumerate(headers):
        if any(kw in h for kw in ["phone", "mobile", "contact", "number", "tel"]):
            phone_idx = idx
        elif any(kw in h for kw in ["name", "customer", "lead", "person"]):
            if name_idx == -1 or "full" in h:
                name_idx = idx
        elif "email" in h or "mail" in h:
            email_idx = idx
        elif any(kw in h for kw in ["city", "location", "town"]):
            city_idx = idx
        elif any(kw in h for kw in ["shop", "store", "company", "firm"]):
            shop_idx = idx
        elif any(kw in h for kw in ["business", "category", "type"]):
            biz_idx = idx
        elif any(kw in h for kw in ["address", "site", "street"]):
            address_idx = idx

    for row in rows[1:]:
        if not row or all(not cell.strip() for cell in row):
            continue
        
        def get_val(idx, default=""):
            if idx != -1 and idx < len(row):
                return row[idx].strip()
            return default
        
        phone_val = get_val(phone_idx)
        name_val = get_val(name_idx)
        
        if not phone_val and not name_val:
            continue
            
        leads_data.append({
            "customer_name": name_val or "Sheets Customer",
            "phone": phone_val,
            "email": get_val(email_idx),
            "city": get_val(city_idx),
            "shop_name": get_val(shop_idx),
            "business_type": get_val(biz_idx),
            "address": get_val(address_idx)
        })
    return leads_data


def run_sheets_sync_internal(db: Session, ws_manager) -> dict:
    url = get_setting(db, "sheets_url")
    connected = get_setting(db, "sheets_connected")
    if not url or connected != "Connected":
        return {"status": "skipped", "reason": "Not connected or empty URL"}
    
    export_url = get_csv_export_url(url)
    if not export_url:
        set_setting(db, "sheets_sync_status", "Failed (Invalid URL)")
        db.commit()
        return {"status": "failed", "reason": "Invalid Spreadsheet URL"}
        
    try:
        csv_text = fetch_csv_content(export_url)
        leads_data = parse_csv_leads(csv_text)
    except Exception as e:
        err_msg = f"Fetch failed: {str(e)}"
        set_setting(db, "sheets_sync_status", f"Failed ({err_msg})")
        db.commit()
        return {"status": "failed", "reason": err_msg}

    imported = 0
    skipped = 0
    failed = 0
    
    from routers.leads import _next_lead_number
    from models import log_lead_activity
    
    for item in leads_data:
        raw_phone = item["phone"]
        # Normalize phone to last 10 digits
        from auth_utils import normalize_phone
        clean_phone = normalize_phone(raw_phone)
        if not clean_phone or len(clean_phone) < 10:
            failed += 1
            continue
        
        # Deduplication against database leads and customers
        existing_lead = db.query(models.Lead).filter(models.Lead.phone == clean_phone).first()
        existing_cust = db.query(models.Customer).filter(models.Customer.phone == clean_phone).first()
        if existing_lead or existing_cust:
            skipped += 1
            continue
            
        try:
            lead = models.Lead(
                id=str(uuid.uuid4()),
                lead_number=_next_lead_number(db),
                salesman_id="",
                salesman_name="",
                customer_name=item["customer_name"],
                phone=clean_phone,
                shop_name=item["shop_name"],
                address=item.get("address", ""),
                city=item["city"],
                pincode="",
                business_type=item["business_type"],
                remarks="[]",
                follow_up_date="",
                latitude=None,
                longitude=None,
                photo="",
                status="New Lead",
                lead_source="Online",
                created_at=int(time.time() * 1000),
                updated_at=int(time.time() * 1000),
                created_by="Google Sheet Sync",
                current_owner="Google Sheet Sync",
                last_updated_by="Google Sheet Sync"
            )
            db.add(lead)
            db.flush()
            
            log_lead_activity(db, lead.id, lead.lead_number, "Google Sheet Sync", "System", "Lead Created", "", "")
            imported += 1
            
            # Broadcast WebSocket event
            from websocket_manager import broadcast_event
            lead_data = {
                "id": lead.id,
                "lead_number": lead.lead_number,
                "salesman_id": lead.salesman_id or "",
                "salesman_name": lead.salesman_name or "",
                "customer_name": lead.customer_name,
                "phone": lead.phone or "",
                "shop_name": lead.shop_name or "",
                "address": lead.address or "",
                "city": lead.city or "",
                "pincode": lead.pincode or "",
                "business_type": lead.business_type or "",
                "remarks": lead.remarks or "",
                "follow_up_date": lead.follow_up_date or "",
                "latitude": lead.latitude,
                "longitude": lead.longitude,
                "photo": lead.photo or "",
                "status": lead.status or "New Lead",
                "lead_source": lead.lead_source or "Online",
                "assigned_to": lead.assigned_to or "",
                "created_by": lead.created_by or "",
                "current_owner": lead.current_owner or "",
                "last_updated_by": lead.last_updated_by or "",
                "created_note": lead.created_note or "",
                "created_note_by": lead.created_note_by or "",
                "created_note_date": lead.created_note_date or "",
                "created_note_time": lead.created_note_time or "",
                "created_at": lead.created_at,
                "updated_at": lead.updated_at,
                "store_images_json": lead.store_images_json or "[]",
                "store_videos_json": lead.store_videos_json or "[]",
                "store_width": lead.store_width,
                "store_length": lead.store_length,
                "store_height": lead.store_height,
                "store_area": lead.store_area,
            }
            broadcast_event("lead_created", lead_data)
                    
        except Exception as e:
            failed += 1
            logger.error(f"Failed to save Google sheet sync row: {e}")
            
    # Update Sync Stats
    now_ms = int(time.time() * 1000)
    set_setting(db, "sheets_last_sync_time", str(now_ms))
    set_setting(db, "sheets_stats_total", str(len(leads_data)))
    set_setting(db, "sheets_stats_imported", str(imported))
    set_setting(db, "sheets_stats_skipped", str(skipped))
    set_setting(db, "sheets_stats_failed", str(failed))
    set_setting(db, "sheets_sync_status", "Success")
    db.commit()
    
    return {
        "status": "success",
        "total": len(leads_data),
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "last_sync_time": now_ms
    }


class ConnectRequest(BaseModel):
    url: str


@router.post("/connect")
def connect_sheets_sync(payload: ConnectRequest, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    if not payload.url.strip():
        raise HTTPException(status_code=400, detail="Sheet URL cannot be empty")
    
    spreadsheet_id = extract_spreadsheet_id(payload.url)
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Invalid Google Sheets URL format")
        
    set_setting(db, "sheets_url", payload.url.strip())
    set_setting(db, "sheets_connected", "Connected")
    set_setting(db, "sheets_sync_status", "Connected")
    db.commit()
    return {"status": "connected", "url": payload.url.strip()}


@router.post("/disconnect")
def disconnect_sheets_sync(db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    set_setting(db, "sheets_url", "")
    set_setting(db, "sheets_connected", "Disconnected")
    set_setting(db, "sheets_sync_status", "Disconnected")
    set_setting(db, "sheets_last_sync_time", "")
    set_setting(db, "sheets_stats_total", "0")
    set_setting(db, "sheets_stats_imported", "0")
    set_setting(db, "sheets_stats_skipped", "0")
    set_setting(db, "sheets_stats_failed", "0")
    db.commit()
    return {"status": "disconnected"}


@router.post("/sync")
async def trigger_manual_sync(request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    ws_manager = request.app.state.ws_manager
    import asyncio
    res = await asyncio.to_thread(run_sheets_sync_internal, db, ws_manager)
    return res


@router.get("/status")
def get_sheets_sync_status(db: Session = Depends(get_db), current_user: CurrentUser = Depends(RoleChecker(["admin"]))):
    return {
        "url": get_setting(db, "sheets_url"),
        "connected": get_setting(db, "sheets_connected") == "Connected",
        "sync_status": get_setting(db, "sheets_sync_status") or "Disconnected",
        "last_sync_time": int(get_setting(db, "sheets_last_sync_time")) if get_setting(db, "sheets_last_sync_time") else None,
        "stats": {
            "total": int(get_setting(db, "sheets_stats_total")) if get_setting(db, "sheets_stats_total") else 0,
            "imported": int(get_setting(db, "sheets_stats_imported")) if get_setting(db, "sheets_stats_imported") else 0,
            "skipped": int(get_setting(db, "sheets_stats_skipped")) if get_setting(db, "sheets_stats_skipped") else 0,
            "failed": int(get_setting(db, "sheets_stats_failed")) if get_setting(db, "sheets_stats_failed") else 0
        }
    }


# Auto sync loop runner for Lifespan
async def run_auto_sync_loop(app):
    import asyncio
    from database import SessionLocal
    # Auto-run every 5 minutes (300 seconds)
    while True:
        await asyncio.sleep(300)
        db = SessionLocal()
        try:
            ws_manager = getattr(app.state, "ws_manager", None)
            await asyncio.to_thread(run_sheets_sync_internal, db, ws_manager)
        except Exception as e:
            logger.error(f"Auto sheets sync cycle error: {e}")
        finally:
            db.close()
