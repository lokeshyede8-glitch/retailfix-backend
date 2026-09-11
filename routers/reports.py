"""
Reports & Analytics Router
Enterprise-grade analytics for RetailFix CRM
Covers: Dashboard KPIs, Revenue, Leads, Customers, Quotations,
        Payments, GST, Outstanding, Salesman Performance, Telecaller Performance,
        CSV/Excel Export
Security: Admin = full access; Salesman/Telecaller = own data only
"""

import io
import csv
import time
import json
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case, distinct

from database import get_db
import models
from auth_utils import get_current_user, RoleChecker, CurrentUser

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])


# ─────────────────────────────────────────────
#  Date Range Helpers
# ─────────────────────────────────────────────

def _today_range():
    """Return (start_ts_ms, end_ts_ms) for today."""
    today = datetime.date.today()
    start = datetime.datetime(today.year, today.month, today.day, 0, 0, 0)
    end   = datetime.datetime(today.year, today.month, today.day, 23, 59, 59)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

def _yesterday_range():
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    start = datetime.datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0)
    end   = datetime.datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, 59)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

def _last_n_days_range(n: int):
    end_dt   = datetime.datetime.now()
    start_dt = end_dt - datetime.timedelta(days=n)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)

def _current_month_range():
    today = datetime.date.today()
    start = datetime.datetime(today.year, today.month, 1, 0, 0, 0)
    # Last day of month
    if today.month == 12:
        end = datetime.datetime(today.year + 1, 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
    else:
        end = datetime.datetime(today.year, today.month + 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

def _current_year_range():
    today = datetime.date.today()
    start = datetime.datetime(today.year, 1, 1, 0, 0, 0)
    end   = datetime.datetime(today.year, 12, 31, 23, 59, 59)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

def _custom_range(date_from: str, date_to: str):
    """Parse YYYY-MM-DD strings."""
    try:
        start = datetime.datetime.strptime(date_from, "%Y-%m-%d")
        end   = datetime.datetime.strptime(date_to,   "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        return int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

def get_date_range(
    period: str,
    date_from: Optional[str] = None,
    date_to:   Optional[str] = None,
):
    """Resolve period string to (start_ms, end_ms)."""
    p = (period or "month").lower()
    if p == "today":
        return _today_range()
    elif p == "yesterday":
        return _yesterday_range()
    elif p == "7days":
        return _last_n_days_range(7)
    elif p == "30days":
        return _last_n_days_range(30)
    elif p == "month":
        return _current_month_range()
    elif p == "year":
        return _current_year_range()
    elif p == "custom":
        if not date_from or not date_to:
            raise HTTPException(status_code=400, detail="date_from and date_to required for custom period.")
        return _custom_range(date_from, date_to)
    else:
        return _current_month_range()

def fmt_money(val) -> float:
    return round(float(val or 0), 2)


# ─────────────────────────────────────────────
#  1. ADMIN DASHBOARD KPIs
# ─────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"])),
):
    """
    Admin-only comprehensive dashboard KPIs.
    Returns today's counts + monthly + yearly summaries.
    """
    today_start, today_end = _today_range()
    month_start, month_end = _current_month_range()
    year_start,  year_end  = _current_year_range()

    # ── TODAY ──────────────────────────────────────────────────────────────────

    # Today's Leads
    today_leads = db.query(func.count(models.Lead.id)).filter(
        models.Lead.created_at >= today_start,
        models.Lead.created_at <= today_end
    ).scalar() or 0

    # Today's Customers
    today_customers = db.query(func.count(models.Customer.id)).filter(
        models.Customer.created_at >= today_start,
        models.Customer.created_at <= today_end
    ).scalar() or 0

    # Today's Quotations
    today_quotations = db.query(func.count(models.Quotation.id)).filter(
        models.Quotation.created_at >= today_start,
        models.Quotation.created_at <= today_end
    ).scalar() or 0

    # Today's Revenue (sum of payments made today)
    today_revenue = db.query(func.sum(models.Payment.amount)).filter(
        models.Payment.payment_date >= today_start,
        models.Payment.payment_date <= today_end
    ).scalar() or 0.0

    # Today's Payments (count)
    today_payments = db.query(func.count(models.Payment.id)).filter(
        models.Payment.payment_date >= today_start,
        models.Payment.payment_date <= today_end
    ).scalar() or 0

    # Today's Followups (scheduled for today)
    today_str = datetime.date.today().isoformat()
    today_followups = db.query(func.count(models.LeadFollowup.id)).filter(
        models.LeadFollowup.follow_up_date == today_str
    ).scalar() or 0

    # Today's Visits (salesman activity logs created today)
    today_visits = db.query(func.count(models.SalesmanActivityLog.id)).filter(
        models.SalesmanActivityLog.created_at >= today_start,
        models.SalesmanActivityLog.created_at <= today_end
    ).scalar() or 0

    # Pending Tasks (pending followups total)
    pending_tasks = db.query(func.count(models.LeadFollowup.id)).filter(
        models.LeadFollowup.status == "Pending"
    ).scalar() or 0

    # Completed Tasks (completed followups total)
    completed_tasks = db.query(func.count(models.LeadFollowup.id)).filter(
        models.LeadFollowup.status == "Completed"
    ).scalar() or 0

    # ── MONTHLY ────────────────────────────────────────────────────────────────

    monthly_revenue = db.query(func.sum(models.Payment.amount)).filter(
        models.Payment.payment_date >= month_start,
        models.Payment.payment_date <= month_end
    ).scalar() or 0.0

    monthly_quotations = db.query(func.count(models.Quotation.id)).filter(
        models.Quotation.created_at >= month_start,
        models.Quotation.created_at <= month_end
    ).scalar() or 0

    monthly_leads = db.query(func.count(models.Lead.id)).filter(
        models.Lead.created_at >= month_start,
        models.Lead.created_at <= month_end
    ).scalar() or 0

    monthly_customers = db.query(func.count(models.Customer.id)).filter(
        models.Customer.created_at >= month_start,
        models.Customer.created_at <= month_end
    ).scalar() or 0

    # ── YEARLY ─────────────────────────────────────────────────────────────────

    yearly_revenue = db.query(func.sum(models.Payment.amount)).filter(
        models.Payment.payment_date >= year_start,
        models.Payment.payment_date <= year_end
    ).scalar() or 0.0

    yearly_quotations = db.query(func.count(models.Quotation.id)).filter(
        models.Quotation.created_at >= year_start,
        models.Quotation.created_at <= year_end
    ).scalar() or 0

    yearly_leads = db.query(func.count(models.Lead.id)).filter(
        models.Lead.created_at >= year_start,
        models.Lead.created_at <= year_end
    ).scalar() or 0

    # ── CONVERSION RATE ────────────────────────────────────────────────────────
    total_leads = db.query(func.count(models.Lead.id)).scalar() or 0
    converted_leads = db.query(func.count(models.Lead.id)).filter(
        models.Lead.status == "Converted"
    ).scalar() or 0
    conversion_rate = round((converted_leads / total_leads * 100), 1) if total_leads > 0 else 0.0

    # ── LEAD PIPELINE ──────────────────────────────────────────────────────────
    pipeline_statuses = ["New Lead", "Contacted", "Visited", "Converted", "Lost"]
    lead_pipeline = {}
    for s in pipeline_statuses:
        count = db.query(func.count(models.Lead.id)).filter(models.Lead.status == s).scalar() or 0
        lead_pipeline[s] = count

    # ── OUTSTANDING AMOUNT ─────────────────────────────────────────────────────
    # Total quotation value - total payments received
    total_invoiced = db.query(func.sum(models.Quotation.grand_total)).filter(
        models.Quotation.status.notin_(["Draft", "Cancelled"])
    ).scalar() or 0.0
    total_collected = db.query(func.sum(models.Payment.amount)).scalar() or 0.0
    outstanding_amount = max(0.0, total_invoiced - total_collected)

    # ── AVERAGE TICKET SIZE ────────────────────────────────────────────────────
    avg_ticket = db.query(func.avg(models.Quotation.grand_total)).filter(
        models.Quotation.status.notin_(["Draft", "Cancelled"])
    ).scalar() or 0.0

    # ── TOTAL COUNTS (all time) ────────────────────────────────────────────────
    total_customers = db.query(func.count(models.Customer.id)).scalar() or 0
    total_quotations = db.query(func.count(models.Quotation.id)).scalar() or 0
    total_payments = db.query(func.sum(models.Payment.amount)).scalar() or 0.0

    return {
        "today": {
            "leads": today_leads,
            "customers": today_customers,
            "quotations": today_quotations,
            "revenue": fmt_money(today_revenue),
            "payments": today_payments,
            "followups": today_followups,
            "visits": today_visits,
        },
        "tasks": {
            "pending": pending_tasks,
            "completed": completed_tasks,
        },
        "monthly": {
            "revenue": fmt_money(monthly_revenue),
            "quotations": monthly_quotations,
            "leads": monthly_leads,
            "customers": monthly_customers,
        },
        "yearly": {
            "revenue": fmt_money(yearly_revenue),
            "quotations": yearly_quotations,
            "leads": yearly_leads,
        },
        "totals": {
            "leads": total_leads,
            "customers": total_customers,
            "quotations": total_quotations,
            "revenue": fmt_money(total_payments),
            "outstanding": fmt_money(outstanding_amount),
            "avg_ticket_size": fmt_money(avg_ticket),
        },
        "conversion_rate": conversion_rate,
        "lead_pipeline": lead_pipeline,
    }


# ─────────────────────────────────────────────
#  2. REVENUE REPORT
# ─────────────────────────────────────────────

@router.get("/revenue")
def get_revenue_report(
    period:     str = Query("month"),
    date_from:  Optional[str] = Query(None),
    date_to:    Optional[str] = Query(None),
    group_by:   str = Query("day"),   # day | month
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"])),
):
    start_ms, end_ms = get_date_range(period, date_from, date_to)

    # Fetch payments in range
    payments = db.query(models.Payment).filter(
        models.Payment.payment_date >= start_ms,
        models.Payment.payment_date <= end_ms
    ).all()

    # Fetch quotations created in range
    quotations = db.query(models.Quotation).filter(
        models.Quotation.created_at >= start_ms,
        models.Quotation.created_at <= end_ms
    ).all()

    # Group payments by day/month
    trend_map: dict = {}
    for p in payments:
        dt = datetime.datetime.fromtimestamp(p.payment_date / 1000)
        if group_by == "month":
            key = dt.strftime("%Y-%m")
        else:
            key = dt.strftime("%Y-%m-%d")
        trend_map[key] = trend_map.get(key, 0.0) + (p.amount or 0.0)

    # Sort keys
    sorted_trend = [{"date": k, "revenue": round(v, 2)} for k, v in sorted(trend_map.items())]

    # Payment mode breakdown
    mode_map: dict = {}
    for p in payments:
        mode = p.payment_mode or "Unknown"
        mode_map[mode] = mode_map.get(mode, 0.0) + (p.amount or 0.0)
    mode_breakdown = [{"mode": k, "amount": round(v, 2)} for k, v in mode_map.items()]

    total_revenue = sum(p.amount or 0.0 for p in payments)
    total_quotation_value = sum(q.grand_total or 0.0 for q in quotations)
    avg_payment = total_revenue / len(payments) if payments else 0.0

    # GST collected
    total_gst = sum(q.gst_amount or 0.0 for q in quotations if q.status not in ("Draft", "Cancelled"))
    total_cgst = sum(q.cgst or 0.0 for q in quotations if q.status not in ("Draft", "Cancelled"))
    total_sgst = sum(q.sgst or 0.0 for q in quotations if q.status not in ("Draft", "Cancelled"))
    total_igst = sum(q.igst or 0.0 for q in quotations if q.status not in ("Draft", "Cancelled"))

    return {
        "period": period,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "summary": {
            "total_revenue_collected": fmt_money(total_revenue),
            "total_quotation_value": fmt_money(total_quotation_value),
            "avg_payment_amount": fmt_money(avg_payment),
            "payment_count": len(payments),
            "quotation_count": len(quotations),
            "total_gst": fmt_money(total_gst),
            "total_cgst": fmt_money(total_cgst),
            "total_sgst": fmt_money(total_sgst),
            "total_igst": fmt_money(total_igst),
        },
        "trend": sorted_trend,
        "mode_breakdown": mode_breakdown,
    }


# ─────────────────────────────────────────────
#  3. LEADS REPORT
# ─────────────────────────────────────────────

@router.get("/leads")
def get_leads_report(
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    salesman_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    role_lower = current_user.role.lower()

    start_ms, end_ms = get_date_range(period, date_from, date_to)

    q = db.query(models.Lead).filter(
        models.Lead.created_at >= start_ms,
        models.Lead.created_at <= end_ms
    )
    # Role-based scoping
    if role_lower == "salesman":
        q = q.filter(models.Lead.salesman_id == current_user.id)
    elif role_lower == "telecaller":
        q = q.filter(models.Lead.assigned_to == current_user.username)
    elif salesman_id:
        q = q.filter(models.Lead.salesman_id == salesman_id)

    leads = q.all()

    # Status breakdown
    status_map: dict = {}
    for lead in leads:
        s = lead.status or "New Lead"
        status_map[s] = status_map.get(s, 0) + 1

    # Lead source breakdown
    source_map: dict = {}
    for lead in leads:
        src = lead.lead_source or "Manual"
        source_map[src] = source_map.get(src, 0) + 1

    # Business type breakdown
    btype_map: dict = {}
    for lead in leads:
        bt = lead.business_type or "Unknown"
        btype_map[bt] = btype_map.get(bt, 0) + 1

    # Daily trend
    trend_map: dict = {}
    for lead in leads:
        dt = datetime.datetime.fromtimestamp((lead.created_at or 0) / 1000)
        key = dt.strftime("%Y-%m-%d")
        trend_map[key] = trend_map.get(key, 0) + 1
    sorted_trend = [{"date": k, "count": v} for k, v in sorted(trend_map.items())]

    total = len(leads)
    converted = status_map.get("Converted", 0)
    lost = status_map.get("Lost", 0)
    conversion_rate = round((converted / total * 100), 1) if total > 0 else 0.0

    return {
        "period": period,
        "summary": {
            "total": total,
            "converted": converted,
            "lost": lost,
            "conversion_rate": conversion_rate,
        },
        "pipeline": status_map,
        "source_breakdown": source_map,
        "business_type_breakdown": btype_map,
        "trend": sorted_trend,
    }


# ─────────────────────────────────────────────
#  4. CUSTOMERS REPORT
# ─────────────────────────────────────────────

@router.get("/customers")
def get_customers_report(
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"])),
):
    start_ms, end_ms = get_date_range(period, date_from, date_to)

    customers_in_period = db.query(models.Customer).filter(
        models.Customer.created_at >= start_ms,
        models.Customer.created_at <= end_ms
    ).all()

    all_customers = db.query(models.Customer).all()

    # City breakdown
    city_map: dict = {}
    for c in all_customers:
        city = (c.city or "Unknown").strip() or "Unknown"
        city_map[city] = city_map.get(city, 0) + 1

    # Growth trend
    trend_map: dict = {}
    for c in customers_in_period:
        dt = datetime.datetime.fromtimestamp((c.created_at or 0) / 1000)
        key = dt.strftime("%Y-%m-%d")
        trend_map[key] = trend_map.get(key, 0) + 1
    sorted_trend = [{"date": k, "count": v} for k, v in sorted(trend_map.items())]

    # Top customers by total quotation value
    top_customers_raw = (
        db.query(
            models.Quotation.customer_id,
            models.Quotation.customer_name,
            func.sum(models.Quotation.grand_total).label("total_value"),
            func.count(models.Quotation.id).label("quote_count"),
        )
        .filter(models.Quotation.customer_id.isnot(None))
        .group_by(models.Quotation.customer_id, models.Quotation.customer_name)
        .order_by(func.sum(models.Quotation.grand_total).desc())
        .limit(10)
        .all()
    )
    top_customers = [
        {"customer_id": r[0], "name": r[1], "total_value": fmt_money(r[2]), "quote_count": r[3]}
        for r in top_customers_raw
    ]

    return {
        "period": period,
        "summary": {
            "total_customers": len(all_customers),
            "new_in_period": len(customers_in_period),
        },
        "city_breakdown": city_map,
        "trend": sorted_trend,
        "top_customers": top_customers,
    }


# ─────────────────────────────────────────────
#  5. QUOTATIONS REPORT
# ─────────────────────────────────────────────

@router.get("/quotations")
def get_quotations_report(
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")

    start_ms, end_ms = get_date_range(period, date_from, date_to)

    q_query = db.query(models.Quotation).filter(
        models.Quotation.created_at >= start_ms,
        models.Quotation.created_at <= end_ms
    )
    if role_lower == "salesman":
        # Salesman sees only quotations for their leads
        salesman_phones = [
            l.phone for l in db.query(models.Lead).filter(
                models.Lead.salesman_id == current_user.id
            ).all()
        ]
        q_query = q_query.filter(models.Quotation.customer_phone.in_(salesman_phones))

    quotations = q_query.all()

    # Status breakdown
    status_map: dict = {}
    for q in quotations:
        s = q.status or "Draft"
        status_map[s] = status_map.get(s, 0) + 1

    # Payment status breakdown
    pay_status_map: dict = {}
    for q in quotations:
        ps = q.payment_status or "Pending"
        pay_status_map[ps] = pay_status_map.get(ps, 0) + 1

    # Daily trend
    trend_map: dict = {}
    value_trend: dict = {}
    for q in quotations:
        dt = datetime.datetime.fromtimestamp((q.created_at or 0) / 1000)
        key = dt.strftime("%Y-%m-%d")
        trend_map[key] = trend_map.get(key, 0) + 1
        value_trend[key] = value_trend.get(key, 0.0) + (q.grand_total or 0.0)
    sorted_trend = [
        {"date": k, "count": trend_map[k], "value": round(value_trend[k], 2)}
        for k in sorted(trend_map.keys())
    ]

    total_value = sum(q.grand_total or 0.0 for q in quotations)
    avg_value   = total_value / len(quotations) if quotations else 0.0
    approved_value = sum(
        q.grand_total or 0.0 for q in quotations
        if q.status not in ("Draft", "Cancelled")
    )

    return {
        "period": period,
        "summary": {
            "total_count": len(quotations),
            "total_value": fmt_money(total_value),
            "approved_value": fmt_money(approved_value),
            "avg_value": fmt_money(avg_value),
        },
        "status_breakdown": status_map,
        "payment_status_breakdown": pay_status_map,
        "trend": sorted_trend,
    }


# ─────────────────────────────────────────────
#  6. PAYMENTS REPORT
# ─────────────────────────────────────────────

@router.get("/payments")
def get_payments_report(
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")

    start_ms, end_ms = get_date_range(period, date_from, date_to)

    pay_query = db.query(models.Payment).filter(
        models.Payment.payment_date >= start_ms,
        models.Payment.payment_date <= end_ms
    )
    if role_lower == "salesman":
        salesman_phones = [
            l.phone for l in db.query(models.Lead).filter(
                models.Lead.salesman_id == current_user.id
            ).all()
        ]
        pay_query = pay_query.join(
            models.Quotation,
            models.Payment.quotation_id == models.Quotation.id
        ).filter(models.Quotation.customer_phone.in_(salesman_phones))

    payments = pay_query.all()

    # Payment type breakdown: Advance / Final / Other
    ptype_map: dict = {}
    for p in payments:
        pt = p.payment_type or "Other"
        ptype_map[pt] = ptype_map.get(pt, 0.0) + (p.amount or 0.0)

    # Mode breakdown
    mode_map: dict = {}
    for p in payments:
        mode = p.payment_mode or "Unknown"
        mode_map[mode] = mode_map.get(mode, 0.0) + (p.amount or 0.0)

    # Daily trend
    trend_map: dict = {}
    for p in payments:
        dt = datetime.datetime.fromtimestamp((p.payment_date or 0) / 1000)
        key = dt.strftime("%Y-%m-%d")
        trend_map[key] = trend_map.get(key, 0.0) + (p.amount or 0.0)
    sorted_trend = [{"date": k, "amount": round(v, 2)} for k, v in sorted(trend_map.items())]

    total = sum(p.amount or 0.0 for p in payments)
    advance = ptype_map.get("Advance", 0.0)
    final   = ptype_map.get("Final",   0.0)

    return {
        "period": period,
        "summary": {
            "total_collected": fmt_money(total),
            "advance_collected": fmt_money(advance),
            "final_collected": fmt_money(final),
            "payment_count": len(payments),
            "avg_payment": fmt_money(total / len(payments) if payments else 0.0),
        },
        "type_breakdown": {k: round(v, 2) for k, v in ptype_map.items()},
        "mode_breakdown": {k: round(v, 2) for k, v in mode_map.items()},
        "trend": sorted_trend,
    }


# ─────────────────────────────────────────────
#  7. GST REPORT
# ─────────────────────────────────────────────

@router.get("/gst")
def get_gst_report(
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"])),
):
    start_ms, end_ms = get_date_range(period, date_from, date_to)

    quotations = db.query(models.Quotation).filter(
        models.Quotation.created_at >= start_ms,
        models.Quotation.created_at <= end_ms,
        models.Quotation.status.notin_(["Draft", "Cancelled"])
    ).all()

    # Compute GST slab breakdown from items JSON
    slab_map: dict = {}  # gst_rate -> {taxable, cgst, sgst, igst, total_gst}

    total_taxable = 0.0
    total_cgst    = 0.0
    total_sgst    = 0.0
    total_igst    = 0.0
    total_gst     = 0.0
    total_invoice = 0.0

    for q in quotations:
        total_invoice += q.grand_total or 0.0
        total_cgst    += q.cgst    or 0.0
        total_sgst    += q.sgst    or 0.0
        total_igst    += q.igst    or 0.0
        total_gst     += q.gst_amount or 0.0
        total_taxable += (q.grand_total or 0.0) - (q.gst_amount or 0.0) - (q.delivery or 0.0)

        # Per-item GST slab tracking
        try:
            items = json.loads(q.items_json or "[]")
            for item in items:
                rate = float(item.get("gst_rate") or q.gst_rate or 18)
                rate_key = f"{int(rate)}%"
                line_total = float(item.get("line_total") or 0.0)

                if q.gst_type == "inclusive":
                    item_taxable = line_total / (1 + rate / 100)
                    item_gst_amt = line_total - item_taxable
                else:
                    item_taxable = line_total
                    item_gst_amt = line_total * (rate / 100)

                if rate_key not in slab_map:
                    slab_map[rate_key] = {"taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total_gst": 0.0}

                slab_map[rate_key]["taxable"] += item_taxable
                if q.gst_mode == "split":
                    slab_map[rate_key]["cgst"] += item_gst_amt / 2
                    slab_map[rate_key]["sgst"] += item_gst_amt / 2
                else:
                    slab_map[rate_key]["igst"] += item_gst_amt
                slab_map[rate_key]["total_gst"] += item_gst_amt
        except Exception:
            pass

    # Round slab values
    slab_breakdown = [
        {
            "rate": k,
            "taxable": round(v["taxable"], 2),
            "cgst": round(v["cgst"], 2),
            "sgst": round(v["sgst"], 2),
            "igst": round(v["igst"], 2),
            "total_gst": round(v["total_gst"], 2),
        }
        for k, v in sorted(slab_map.items())
    ]

    return {
        "period": period,
        "summary": {
            "total_invoice_value": fmt_money(total_invoice),
            "total_taxable_value": fmt_money(total_taxable),
            "total_cgst": fmt_money(total_cgst),
            "total_sgst": fmt_money(total_sgst),
            "total_igst": fmt_money(total_igst),
            "total_gst_collected": fmt_money(total_gst),
            "quotation_count": len(quotations),
        },
        "slab_breakdown": slab_breakdown,
    }


# ─────────────────────────────────────────────
#  8. OUTSTANDING REPORT
# ─────────────────────────────────────────────

@router.get("/outstanding")
def get_outstanding_report(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"])),
):
        # Get all quotations that aren't Draft or Cancelled
    quotations = db.query(models.Quotation).filter(
        models.Quotation.status.notin_(["Draft", "Cancelled"]),
        models.Quotation.payment_status.notin_(["Paid"])
    ).all()

    # For each quotation get total paid
    results = []
    total_outstanding = 0.0
    overdue_count = 0

    today = datetime.date.today()

    for q in quotations:
        payments = db.query(func.sum(models.Payment.amount)).filter(
            models.Payment.quotation_id == q.id
        ).scalar() or 0.0

        outstanding = max(0.0, (q.grand_total or 0.0) - payments)
        if outstanding <= 0:
            continue

        total_outstanding += outstanding

        # Determine overdue (simplified: created more than 30 days ago with pending payment)
        created_dt = datetime.datetime.fromtimestamp((q.created_at or 0) / 1000).date()
        days_pending = (today - created_dt).days
        is_overdue = days_pending > 30

        if is_overdue:
            overdue_count += 1

        results.append({
            "quote_number": q.quote_number,
            "quotation_id": q.id,
            "customer_name": q.customer_name,
            "customer_phone": q.customer_phone,
            "date": q.date,
            "grand_total": fmt_money(q.grand_total),
            "paid_amount": fmt_money(payments),
            "outstanding": fmt_money(outstanding),
            "payment_status": q.payment_status,
            "status": q.status,
            "days_pending": days_pending,
            "is_overdue": is_overdue,
        })

    # Sort by outstanding descending
    results.sort(key=lambda x: x["outstanding"], reverse=True)

    return {
        "summary": {
            "total_outstanding": fmt_money(total_outstanding),
            "pending_count": len(results),
            "overdue_count": overdue_count,
        },
        "records": results,
    }


# ─────────────────────────────────────────────
#  9. SALESMAN PERFORMANCE
# ─────────────────────────────────────────────

@router.get("/salesman-performance")
def get_salesman_performance(
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    role_lower = current_user.role.lower()
    if role_lower == "telecaller":
        raise HTTPException(status_code=403, detail="Forbidden")

    start_ms, end_ms = get_date_range(period, date_from, date_to)

    salesmen = db.query(models.Salesman).filter(models.Salesman.active == True).all()

    results = []
    for sm in salesmen:
        # If salesman is requesting their own data only
        if role_lower == "salesman" and sm.id != current_user.id:
            continue

        # Leads assigned
        leads = db.query(models.Lead).filter(
            models.Lead.salesman_id == sm.id,
            models.Lead.created_at >= start_ms,
            models.Lead.created_at <= end_ms
        ).all()
        assigned_leads = len(leads)
        converted_leads = sum(1 for l in leads if l.status == "Converted")
        conversion_rate = round((converted_leads / assigned_leads * 100), 1) if assigned_leads > 0 else 0.0

        # Visits completed (salesman activity logs - any action)
        total_visits = db.query(func.count(models.SalesmanActivityLog.id)).filter(
            models.SalesmanActivityLog.salesman_id == sm.id,
            models.SalesmanActivityLog.created_at >= start_ms,
            models.SalesmanActivityLog.created_at <= end_ms
        ).scalar() or 0

        # Pending visits (followups pending)
        pending_visits = db.query(func.count(models.LeadFollowup.id)).filter(
            models.LeadFollowup.assigned_to == sm.name,
            models.LeadFollowup.status == "Pending"
        ).scalar() or 0

        # Followups completed
        followups_completed = db.query(func.count(models.LeadFollowup.id)).filter(
            models.LeadFollowup.assigned_to == sm.name,
            models.LeadFollowup.status == "Completed"
        ).scalar() or 0

        # Quotation count
        salesman_phones = [l.phone for l in db.query(models.Lead).filter(
            models.Lead.salesman_id == sm.id
        ).all()]

        quotation_count = db.query(func.count(models.Quotation.id)).filter(
            models.Quotation.customer_phone.in_(salesman_phones),
            models.Quotation.created_at >= start_ms,
            models.Quotation.created_at <= end_ms
        ).scalar() or 0

        # Revenue generated (payments for salesman's customers)
        revenue = 0.0
        if salesman_phones:
            rev_rows = (
                db.query(func.sum(models.Payment.amount))
                .join(models.Quotation, models.Payment.quotation_id == models.Quotation.id)
                .filter(
                    models.Quotation.customer_phone.in_(salesman_phones),
                    models.Payment.payment_date >= start_ms,
                    models.Payment.payment_date <= end_ms
                )
                .scalar()
            )
            revenue = float(rev_rows or 0.0)

        # Average response time (first activity after lead creation, in hours)
        avg_response_hours = None
        response_times = []
        for lead in leads:
            first_activity = db.query(models.LeadActivity).filter(
                models.LeadActivity.lead_id == lead.id
            ).order_by(models.LeadActivity.created_at.asc()).first()
            if first_activity and lead.created_at:
                diff_hours = ((first_activity.created_at or 0) - lead.created_at) / 3_600_000
                if 0 <= diff_hours <= 720:  # Cap at 30 days
                    response_times.append(diff_hours)
        if response_times:
            avg_response_hours = round(sum(response_times) / len(response_times), 1)

        results.append({
            "salesman_id": sm.id,
            "salesman_name": sm.name,
            "assigned_leads": assigned_leads,
            "converted_leads": converted_leads,
            "conversion_rate": conversion_rate,
            "completed_visits": total_visits,
            "pending_visits": pending_visits,
            "followups_completed": followups_completed,
            "quotation_count": quotation_count,
            "revenue_generated": fmt_money(revenue),
            "avg_response_hours": avg_response_hours,
        })

    # Sort by revenue for leaderboard
    results.sort(key=lambda x: x["revenue_generated"], reverse=True)

    # Add rank
    for i, r in enumerate(results, 1):
        r["rank"] = i

    return {
        "period": period,
        "leaderboard": results,
        "total_salesmen": len(results),
    }


# ─────────────────────────────────────────────
#  10. TELECALLER PERFORMANCE
# ─────────────────────────────────────────────

@router.get("/telecaller-performance")
def get_telecaller_performance(
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    role_lower = current_user.role.lower()
    if role_lower == "salesman":
        raise HTTPException(status_code=403, detail="Forbidden")

    start_ms, end_ms = get_date_range(period, date_from, date_to)

    telecallers = db.query(models.Telecaller).filter(models.Telecaller.active == True).all()

    results = []
    for tc in telecallers:
        if role_lower == "telecaller" and tc.id != current_user.id:
            continue

        # Telecaller activity logs (calls made)
        calls_query = db.query(func.count(models.TelecallerActivityLog.id)).filter(
            models.TelecallerActivityLog.telecaller_name == tc.name,
            models.TelecallerActivityLog.created_at >= start_ms,
            models.TelecallerActivityLog.created_at <= end_ms
        )
        calls_made = calls_query.scalar() or 0

        # Followups assigned to this telecaller
        followups_assigned = db.query(func.count(models.LeadFollowup.id)).filter(
            models.LeadFollowup.assigned_to == tc.name
        ).scalar() or 0

        followups_completed = db.query(func.count(models.LeadFollowup.id)).filter(
            models.LeadFollowup.assigned_to == tc.name,
            models.LeadFollowup.status == "Completed"
        ).scalar() or 0

        followups_pending = db.query(func.count(models.LeadFollowup.id)).filter(
            models.LeadFollowup.assigned_to == tc.name,
            models.LeadFollowup.status == "Pending"
        ).scalar() or 0

        # Overdue followups
        today_str = datetime.date.today().isoformat()
        followups_overdue = db.query(func.count(models.LeadFollowup.id)).filter(
            models.LeadFollowup.assigned_to == tc.name,
            models.LeadFollowup.status == "Pending",
            models.LeadFollowup.follow_up_date < today_str
        ).scalar() or 0

        # Leads in their queue
        leads_assigned = db.query(func.count(models.Lead.id)).filter(
            models.Lead.assigned_to == tc.name,
            models.Lead.created_at >= start_ms,
            models.Lead.created_at <= end_ms
        ).scalar() or 0

        # Lead qualification rate (Contacted or higher out of total assigned)
        qualified_statuses = ["Contacted", "Visited", "Converted"]
        leads_qualified = db.query(func.count(models.Lead.id)).filter(
            models.Lead.assigned_to == tc.name,
            models.Lead.status.in_(qualified_statuses)
        ).scalar() or 0

        total_assigned_all = db.query(func.count(models.Lead.id)).filter(
            models.Lead.assigned_to == tc.name
        ).scalar() or 0

        qualification_rate = round((leads_qualified / total_assigned_all * 100), 1) if total_assigned_all > 0 else 0.0

        # Customer conversions (leads moved to Converted by this telecaller)
        customer_conversions = db.query(func.count(models.Lead.id)).filter(
            models.Lead.assigned_to == tc.name,
            models.Lead.status == "Converted"
        ).scalar() or 0

        # Activity score (weighted: calls * 1 + followups_completed * 3 + conversions * 10)
        activity_score = (calls_made * 1) + (followups_completed * 3) + (customer_conversions * 10)

        results.append({
            "telecaller_id": tc.id,
            "telecaller_name": tc.name,
            "calls_made": calls_made,
            "leads_assigned": leads_assigned,
            "followups_completed": followups_completed,
            "followups_pending": followups_pending,
            "followups_overdue": followups_overdue,
            "qualification_rate": qualification_rate,
            "customer_conversions": customer_conversions,
            "activity_score": activity_score,
        })

    # Sort by activity score
    results.sort(key=lambda x: x["activity_score"], reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i

    return {
        "period": period,
        "leaderboard": results,
        "total_telecallers": len(results),
    }


# ─────────────────────────────────────────────
#  11. CSV EXPORT
# ─────────────────────────────────────────────

@router.get("/export/csv")
def export_csv(
    report_type: str = Query("revenue"),
    period:    str = Query("month"),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"])),
):
    start_ms, end_ms = get_date_range(period, date_from, date_to)

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "revenue":
        payments = db.query(models.Payment).filter(
            models.Payment.payment_date >= start_ms,
            models.Payment.payment_date <= end_ms
        ).order_by(models.Payment.payment_date.desc()).all()

        writer.writerow(["Date", "Invoice No", "Customer", "Amount", "Type", "Mode", "Transaction ID", "Remarks"])
        for p in payments:
            dt = datetime.datetime.fromtimestamp((p.payment_date or 0) / 1000).strftime("%Y-%m-%d")
            writer.writerow([dt, p.invoice_number or "", "", p.amount, p.payment_type or "", p.payment_mode or "", p.transaction_id or "", p.remarks or ""])

    elif report_type == "quotations":
        quotations = db.query(models.Quotation).filter(
            models.Quotation.created_at >= start_ms,
            models.Quotation.created_at <= end_ms
        ).order_by(models.Quotation.created_at.desc()).all()

        writer.writerow(["Quote No", "Date", "Customer", "Phone", "City", "Subtotal", "GST", "Grand Total", "Status", "Payment Status"])
        for q in quotations:
            writer.writerow([
                q.quote_number, q.date, q.customer_name, q.customer_phone,
                q.customer_city, q.subtotal, q.gst_amount, q.grand_total,
                q.status, q.payment_status
            ])

    elif report_type == "leads":
        leads = db.query(models.Lead).filter(
            models.Lead.created_at >= start_ms,
            models.Lead.created_at <= end_ms
        ).order_by(models.Lead.created_at.desc()).all()

        writer.writerow(["Lead No", "Customer", "Phone", "City", "Business Type", "Source", "Status", "Salesman", "Created"])
        for l in leads:
            dt = datetime.datetime.fromtimestamp((l.created_at or 0) / 1000).strftime("%Y-%m-%d")
            writer.writerow([
                l.lead_number, l.customer_name, l.phone, l.city,
                l.business_type or "", l.lead_source or "", l.status,
                l.salesman_name or "", dt
            ])

    elif report_type == "customers":
        customers = db.query(models.Customer).filter(
            models.Customer.created_at >= start_ms,
            models.Customer.created_at <= end_ms
        ).order_by(models.Customer.created_at.desc()).all()

        writer.writerow(["Name", "Phone", "Email", "City", "Address", "GSTIN", "Created"])
        for c in customers:
            dt = datetime.datetime.fromtimestamp((c.created_at or 0) / 1000).strftime("%Y-%m-%d")
            writer.writerow([c.name, c.phone, c.email or "", c.city or "", c.address or "", c.gstin or "", dt])

    elif report_type == "outstanding":
        quotations = db.query(models.Quotation).filter(
            models.Quotation.status.notin_(["Draft", "Cancelled"]),
            models.Quotation.payment_status.notin_(["Paid"])
        ).all()

        writer.writerow(["Quote No", "Customer", "Phone", "Grand Total", "Paid", "Outstanding", "Status", "Date"])
        for q in quotations:
            paid = db.query(func.sum(models.Payment.amount)).filter(
                models.Payment.quotation_id == q.id
            ).scalar() or 0.0
            outstanding = max(0.0, (q.grand_total or 0.0) - paid)
            if outstanding > 0:
                writer.writerow([
                    q.quote_number, q.customer_name, q.customer_phone,
                    q.grand_total, round(paid, 2), round(outstanding, 2),
                    q.payment_status, q.date
                ])

    else:
        raise HTTPException(status_code=400, detail=f"Unknown report_type: {report_type}")

    output.seek(0)
    filename = f"retailfix_{report_type}_{period}_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ─────────────────────────────────────────────
#  12. MONTHLY TRENDS (12-month view)
# ─────────────────────────────────────────────

@router.get("/monthly-trends")
def get_monthly_trends(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(RoleChecker(["admin"])),
):
    today = datetime.date.today()
    months = []
    for i in range(11, -1, -1):
        year  = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year  -= 1
        months.append((year, month))

    result = []
    for year, month in months:
        start = datetime.datetime(year, month, 1)
        if month == 12:
            end = datetime.datetime(year + 1, 1, 1) - datetime.timedelta(seconds=1)
        else:
            end = datetime.datetime(year, month + 1, 1) - datetime.timedelta(seconds=1)

        start_ms = int(start.timestamp() * 1000)
        end_ms   = int(end.timestamp()   * 1000)

        revenue = db.query(func.sum(models.Payment.amount)).filter(
            models.Payment.payment_date >= start_ms,
            models.Payment.payment_date <= end_ms
        ).scalar() or 0.0

        leads = db.query(func.count(models.Lead.id)).filter(
            models.Lead.created_at >= start_ms,
            models.Lead.created_at <= end_ms
        ).scalar() or 0

        quotations = db.query(func.count(models.Quotation.id)).filter(
            models.Quotation.created_at >= start_ms,
            models.Quotation.created_at <= end_ms
        ).scalar() or 0

        customers = db.query(func.count(models.Customer.id)).filter(
            models.Customer.created_at >= start_ms,
            models.Customer.created_at <= end_ms
        ).scalar() or 0

        label = start.strftime("%b %Y")
        result.append({
            "month": f"{year}-{month:02d}",
            "label": label,
            "revenue": fmt_money(revenue),
            "leads": leads,
            "quotations": quotations,
            "customers": customers,
        })

    return {"trends": result}
