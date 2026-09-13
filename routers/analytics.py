"""
RetailFix Business & Operations Analytics Router
Admin-only comprehensive analytics engine covering the complete software lifecycle:
Lead → Customer → Quotation → Approval → Payment → Production → Material Progress → Completion → Dispatch

All queries run real PostgreSQL database aggregations with prior period comparison.
Security: Admin role strictly enforced on all endpoints via RoleChecker(["admin"]).
"""

import io
import csv
import json
import time
import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case, distinct, desc

from database import get_db
import models
from auth_utils import get_current_user, RoleChecker, CurrentUser

router = APIRouter(
    prefix="/analytics",
    tags=["Business & Operational Analytics"],
    dependencies=[Depends(RoleChecker(["admin"]))]
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. DATE RANGE RESOLVER (with previous period calculation)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_date_ranges(period: str = "month", date_from: Optional[str] = None, date_to: Optional[str] = None):
    """
    Resolves period to:
      (start_ms, end_ms, prev_start_ms, prev_end_ms)
    All timestamps in RetailFix are stored in epoch milliseconds (BigInteger).
    """
    now = datetime.datetime.now()
    today = now.date()
    p = (period or "month").lower()

    if p == "today":
        start = datetime.datetime(today.year, today.month, today.day, 0, 0, 0)
        end = datetime.datetime(today.year, today.month, today.day, 23, 59, 59, 999000)
        prev_start = start - datetime.timedelta(days=1)
        prev_end = end - datetime.timedelta(days=1)
    elif p == "yesterday":
        y = today - datetime.timedelta(days=1)
        start = datetime.datetime(y.year, y.month, y.day, 0, 0, 0)
        end = datetime.datetime(y.year, y.month, y.day, 23, 59, 59, 999000)
        prev_start = start - datetime.timedelta(days=1)
        prev_end = end - datetime.timedelta(days=1)
    elif p == "7days":
        end = datetime.datetime(today.year, today.month, today.day, 23, 59, 59, 999000)
        start = end - datetime.timedelta(days=7) + datetime.timedelta(seconds=1)
        prev_end = start - datetime.timedelta(seconds=1)
        prev_start = prev_end - datetime.timedelta(days=7) + datetime.timedelta(seconds=1)
    elif p == "30days":
        end = datetime.datetime(today.year, today.month, today.day, 23, 59, 59, 999000)
        start = end - datetime.timedelta(days=30) + datetime.timedelta(seconds=1)
        prev_end = start - datetime.timedelta(seconds=1)
        prev_start = prev_end - datetime.timedelta(days=30) + datetime.timedelta(seconds=1)
    elif p == "month":
        start = datetime.datetime(today.year, today.month, 1, 0, 0, 0)
        if today.month == 12:
            end = datetime.datetime(today.year + 1, 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
        else:
            end = datetime.datetime(today.year, today.month + 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
        if today.month == 1:
            prev_start = datetime.datetime(today.year - 1, 12, 1, 0, 0, 0)
            prev_end = datetime.datetime(today.year, 1, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
        else:
            prev_start = datetime.datetime(today.year, today.month - 1, 1, 0, 0, 0)
            prev_end = datetime.datetime(today.year, today.month, 1, 0, 0, 0) - datetime.timedelta(seconds=1)
    elif p == "year":
        start = datetime.datetime(today.year, 1, 1, 0, 0, 0)
        end = datetime.datetime(today.year, 12, 31, 23, 59, 59, 999000)
        prev_start = datetime.datetime(today.year - 1, 1, 1, 0, 0, 0)
        prev_end = datetime.datetime(today.year - 1, 12, 31, 23, 59, 59, 999000)
    elif p == "custom" and date_from and date_to:
        try:
            start = datetime.datetime.strptime(date_from, "%Y-%m-%d")
            end = datetime.datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999000)
            dur = end - start
            prev_end = start - datetime.timedelta(seconds=1)
            prev_start = prev_end - dur
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    else:  # "all" or default fallback
        start = datetime.datetime(2020, 1, 1, 0, 0, 0)
        end = datetime.datetime(2050, 1, 1, 0, 0, 0)
        prev_start = start
        prev_end = end

    return (
        int(start.timestamp() * 1000),
        int(end.timestamp() * 1000),
        int(prev_start.timestamp() * 1000),
        int(prev_end.timestamp() * 1000)
    )


def calc_change_pct(current: float, previous: float) -> Optional[float]:
    if previous is None or previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100.0, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 2. FILTER DROPDOWNS LIST
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/filters")
def get_analytics_filter_options(db: Session = Depends(get_db)):
    """Returns available filter options sourced from real database records."""
    salesmen = [r[0] for r in db.query(models.Salesman.name).filter(models.Salesman.name != "").distinct().all()]
    telecallers = [r[0] for r in db.query(models.Telecaller.name).filter(models.Telecaller.name != "").distinct().all()]
    lead_sources = [r[0] for r in db.query(models.Lead.lead_source).filter(models.Lead.lead_source != "").distinct().all()]
    
    # Customer names
    customers = [r[0] for r in db.query(models.Customer.name).filter(models.Customer.name != "").order_by(models.Customer.name.asc()).limit(100).all()]
    
    # Product names
    products = [r[0] for r in db.query(models.Product.name).filter(models.Product.name != "").order_by(models.Product.name.asc()).limit(100).all()]

    return {
        "salesmen": sorted(salesmen),
        "telecallers": sorted(telecallers),
        "lead_sources": sorted(lead_sources),
        "customers": customers,
        "products": products,
        "quotation_statuses": ["Draft", "Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed", "Cancelled"],
        "payment_statuses": ["Pending", "Advance Paid", "Partial Paid", "Paid", "Overdue"],
        "production_statuses": ["Accepted", "Started", "Processing", "Completed", "Ready for Dispatch", "Rejected", "Cancelled"]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. EXECUTIVE OVERVIEW & LIFECYCLE FUNNEL
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/overview")
def get_analytics_overview(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    salesman: Optional[str] = None,
    telecaller: Optional[str] = None,
    customer: Optional[str] = None,
    status: Optional[str] = None,
    payment_status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Executive summary dashboard KPIs, Complete Lifecycle Funnel, and Attention Required alerts.
    """
    start_ms, end_ms, prev_start_ms, prev_end_ms = resolve_date_ranges(period, date_from, date_to)

    def query_kpis(s_ms: int, e_ms: int):
        # 1. Leads
        l_q = db.query(models.Lead).filter(models.Lead.created_at >= s_ms, models.Lead.created_at <= e_ms)
        if salesman:
            l_q = l_q.filter(models.Lead.salesman_name == salesman)
        if telecaller:
            l_q = l_q.filter(models.Lead.assigned_to == telecaller)
        total_leads = l_q.count()
        converted_leads = l_q.filter(models.Lead.status == "Converted").count()

        # 2. Customers
        c_q = db.query(models.Customer).filter(models.Customer.created_at >= s_ms, models.Customer.created_at <= e_ms)
        if customer:
            c_q = c_q.filter(models.Customer.name == customer)
        total_customers = c_q.count()

        # 3. Quotations
        q_q = db.query(models.Quotation).filter(models.Quotation.created_at >= s_ms, models.Quotation.created_at <= e_ms)
        if customer:
            q_q = q_q.filter(models.Quotation.customer_name == customer)
        if status and status != "All":
            q_q = q_q.filter(models.Quotation.status == status)
        if payment_status and payment_status != "All":
            q_q = q_q.filter(models.Quotation.payment_status == payment_status)
        total_quotes = q_q.count()

        approved_statuses = ["Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed"]
        approved_quotes = q_q.filter(models.Quotation.status.in_(approved_statuses)).count()
        total_quote_val = q_q.with_entities(func.coalesce(func.sum(models.Quotation.grand_total), 0.0)).scalar() or 0.0
        approved_quote_val = q_q.filter(models.Quotation.status.in_(approved_statuses)).with_entities(
            func.coalesce(func.sum(models.Quotation.grand_total), 0.0)
        ).scalar() or 0.0

        # 4. Payments
        p_q = db.query(models.Payment).filter(models.Payment.payment_date >= s_ms, models.Payment.payment_date <= e_ms)
        payment_received = p_q.with_entities(func.coalesce(func.sum(models.Payment.amount), 0.0)).scalar() or 0.0
        
        # Outstanding payment = approved quotation value minus total payments collected on them
        outstanding = max(0.0, approved_quote_val - payment_received)

        # 5. Production Orders
        po_q = db.query(models.ProductionOrder).filter(models.ProductionOrder.created_at >= s_ms, models.ProductionOrder.created_at <= e_ms)
        if salesman:
            po_q = po_q.filter(models.ProductionOrder.sales_person == salesman)
        if customer:
            po_q = po_q.filter(models.ProductionOrder.customer_name == customer)
        if status and status != "All":
            po_q = po_q.filter(models.ProductionOrder.status == status)

        prod_orders = po_q.count()
        completed_orders = po_q.filter(models.ProductionOrder.status.in_(["Completed", "Ready for Dispatch", "Dispatched"])).count()
        ready_dispatch = po_q.filter(models.ProductionOrder.status == "Ready for Dispatch").count()

        conv_rate = round((converted_leads / total_leads * 100.0), 1) if total_leads > 0 else 0.0

        return {
            "total_leads": total_leads,
            "converted_leads": converted_leads,
            "total_customers": total_customers,
            "total_quotations": total_quotes,
            "approved_quotations": approved_quotes,
            "total_quotation_value": round(float(total_quote_val), 2),
            "approved_quotation_value": round(float(approved_quote_val), 2),
            "payment_received": round(float(payment_received), 2),
            "outstanding_payment": round(float(outstanding), 2),
            "production_orders": prod_orders,
            "completed_orders": completed_orders,
            "ready_to_dispatch": ready_dispatch,
            "conversion_rate": conv_rate
        }

    current_kpis = query_kpis(start_ms, end_ms)
    prev_kpis = query_kpis(prev_start_ms, prev_end_ms)

    kpis = {}
    for key, curr_val in current_kpis.items():
        prev_val = prev_kpis.get(key, 0.0)
        kpis[key] = {
            "value": curr_val,
            "previous": prev_val,
            "change_pct": calc_change_pct(curr_val, prev_val)
        }

    # ── LIFECYCLE FUNNEL METRICS ─────────────────────────────────────────────
    funnel_leads = current_kpis["total_leads"]
    funnel_converted = current_kpis["converted_leads"]
    funnel_customers = current_kpis["total_customers"]
    funnel_quotes = current_kpis["total_quotations"]
    funnel_approved = current_kpis["approved_quotations"]
    
    paid_quotes_count = db.query(distinct(models.Payment.quotation_id)).join(
        models.Quotation, models.Quotation.id == models.Payment.quotation_id
    ).filter(models.Quotation.created_at >= start_ms, models.Quotation.created_at <= end_ms).count()
    
    funnel_production = current_kpis["production_orders"]
    funnel_completed = current_kpis["completed_orders"]
    funnel_ready = current_kpis["ready_to_dispatch"]
    
    dispatched_count = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.created_at >= start_ms,
        models.ProductionOrder.created_at <= end_ms,
        models.ProductionOrder.status == "Dispatched"
    ).count()

    lifecycle_funnel = [
        {"stage": "Leads", "count": funnel_leads, "color": "#6366f1"},
        {"stage": "Converted", "count": funnel_converted, "color": "#8b5cf6"},
        {"stage": "Customers", "count": funnel_customers, "color": "#a855f7"},
        {"stage": "Quotations", "count": funnel_quotes, "color": "#ec4899"},
        {"stage": "Approved", "count": funnel_approved, "color": "#3b82f6"},
        {"stage": "Paid Orders", "count": paid_quotes_count, "color": "#06b6d4"},
        {"stage": "Production", "count": funnel_production, "color": "#f59e0b"},
        {"stage": "Completed", "count": funnel_completed, "color": "#10b981"},
        {"stage": "Ready for Dispatch", "count": funnel_ready, "color": "#14b8a6"},
        {"stage": "Dispatched", "count": dispatched_count, "color": "#22c55e"},
    ]

    for i in range(len(lifecycle_funnel)):
        if i == 0:
            lifecycle_funnel[i]["conversion_pct"] = 100.0
        else:
            prev_cnt = lifecycle_funnel[i-1]["count"]
            curr_cnt = lifecycle_funnel[i]["count"]
            lifecycle_funnel[i]["conversion_pct"] = round((curr_cnt / prev_cnt * 100.0), 1) if prev_cnt > 0 else 0.0

    # ── ATTENTION REQUIRED BOTTLENECK ALERTS ──────────────────────────────────
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    overdue_followups = db.query(models.LeadFollowup).filter(
        models.LeadFollowup.status == "Pending",
        models.LeadFollowup.follow_up_date != "",
        models.LeadFollowup.follow_up_date < today_str
    ).count()

    pending_approval_quotes = db.query(models.Quotation).filter(
        models.Quotation.status == "Draft"
    ).count()

    delayed_production = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.status.notin_(["Completed", "Ready for Dispatch", "Dispatched", "Cancelled", "Rejected"]),
        models.ProductionOrder.expected_dispatch != "",
        models.ProductionOrder.expected_dispatch < today_str
    ).count()

    pending_materials_count = db.query(models.ProductionMaterialRequirement).join(
        models.ProductionOrder, models.ProductionOrder.id == models.ProductionMaterialRequirement.production_order_id
    ).filter(
        models.ProductionOrder.status.in_(["Accepted", "Started", "Processing", "In Production"]),
        models.ProductionMaterialRequirement.manufacturing_status != "Completed"
    ).count()

    waiting_dispatch = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.status == "Ready for Dispatch"
    ).count()

    unpaid_approved_quotes = db.query(models.Quotation).filter(
        models.Quotation.status.in_(["Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed"]),
        models.Quotation.payment_status.in_(["Pending", "Partial Paid", "Overdue"])
    ).count()

    bottlenecks = [
        {
            "id": "overdue_followups",
            "title": "Overdue Follow-ups",
            "count": overdue_followups,
            "level": "urgent" if overdue_followups > 0 else "normal",
            "route": "followups",
            "description": "Leads with past follow-up dates requiring immediate telecaller action"
        },
        {
            "id": "pending_approval",
            "title": "Quotations Awaiting Approval",
            "count": pending_approval_quotes,
            "level": "warning" if pending_approval_quotes > 0 else "normal",
            "route": "saved",
            "description": "Draft quotations awaiting customer acceptance or manager approval"
        },
        {
            "id": "unpaid_orders",
            "title": "Pending Payment Receivables",
            "count": unpaid_approved_quotes,
            "level": "warning" if unpaid_approved_quotes > 0 else "normal",
            "route": "receipts",
            "description": "Approved quotations with pending or partial payment balances"
        },
        {
            "id": "delayed_production",
            "title": "Delayed Production Orders",
            "count": delayed_production,
            "level": "urgent" if delayed_production > 0 else "normal",
            "route": "factory",
            "description": "Orders past scheduled dispatch date still on factory floor"
        },
        {
            "id": "pending_materials",
            "title": "Pending Material Workloads",
            "count": pending_materials_count,
            "level": "info" if pending_materials_count > 0 else "normal",
            "route": "factory",
            "description": "Raw material items currently undergoing preparation on the floor"
        },
        {
            "id": "waiting_dispatch",
            "title": "Orders Ready for Dispatch",
            "count": waiting_dispatch,
            "level": "success" if waiting_dispatch > 0 else "normal",
            "route": "factory",
            "description": "Completed manufacturing orders waiting for delivery logistics"
        },
    ]

    return {
        "kpis": kpis,
        "funnel": lifecycle_funnel,
        "bottlenecks": bottlenecks,
        "period": {
            "name": period,
            "start": datetime.datetime.fromtimestamp(start_ms / 1000).strftime("%d %b %Y"),
            "end": datetime.datetime.fromtimestamp(end_ms / 1000).strftime("%d %b %Y")
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. LEAD & CRM ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/leads")
def get_lead_analytics(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    salesman: Optional[str] = None,
    telecaller: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    query = db.query(models.Lead).filter(models.Lead.created_at >= start_ms, models.Lead.created_at <= end_ms)
    if salesman:
        query = query.filter(models.Lead.salesman_name == salesman)
    if telecaller:
        query = query.filter(models.Lead.assigned_to == telecaller)

    leads = query.all()
    total_leads = len(leads)

    status_counts: Dict[str, int] = {}
    for l in leads:
        st = l.status or "New Lead"
        status_counts[st] = status_counts.get(st, 0) + 1

    source_counts: Dict[str, int] = {}
    for l in leads:
        src = l.lead_source or "Direct / Other"
        source_counts[src] = source_counts.get(src, 0) + 1

    daily_trend: Dict[str, int] = {}
    for l in leads:
        dt = datetime.datetime.fromtimestamp(l.created_at / 1000).strftime("%Y-%m-%d")
        daily_trend[dt] = daily_trend.get(dt, 0) + 1

    trend_list = [{"date": k, "count": v} for k, v in sorted(daily_trend.items())]

    lead_ids = [l.id for l in leads]
    pending_followups = 0
    overdue_followups = 0
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    if lead_ids:
        pending_followups = db.query(models.LeadFollowup).filter(
            models.LeadFollowup.lead_id.in_(lead_ids),
            models.LeadFollowup.status == "Pending"
        ).count()

        overdue_followups = db.query(models.LeadFollowup).filter(
            models.LeadFollowup.lead_id.in_(lead_ids),
            models.LeadFollowup.status == "Pending",
            models.LeadFollowup.follow_up_date != "",
            models.LeadFollowup.follow_up_date < today_str
        ).count()

    converted = status_counts.get("Converted", 0)
    conversion_rate = round((converted / total_leads * 100.0), 1) if total_leads > 0 else 0.0

    return {
        "total_leads": total_leads,
        "converted_leads": converted,
        "conversion_rate": conversion_rate,
        "pending_followups": pending_followups,
        "overdue_followups": overdue_followups,
        "status_distribution": [{"label": k, "value": v} for k, v in status_counts.items()],
        "source_distribution": [{"label": k, "value": v} for k, v in source_counts.items()],
        "trend": trend_list
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. SALESMAN & TELECALLER PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sales")
def get_sales_performance(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    salesman: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    salesmen_query = db.query(models.Salesman).filter(models.Salesman.active == True)
    if salesman:
        salesmen_query = salesmen_query.filter(models.Salesman.name == salesman)
    salesmen = salesmen_query.all()

    salesman_metrics = []
    for sm in salesmen:
        sm_leads = db.query(models.Lead).filter(
            models.Lead.salesman_id == sm.id,
            models.Lead.created_at >= start_ms,
            models.Lead.created_at <= end_ms
        ).all()
        leads_count = len(sm_leads)
        converted_count = sum(1 for l in sm_leads if l.status == "Converted")

        q_rows = db.query(models.Quotation).filter(
            or_(models.Quotation.customer_city.ilike(f"%{sm.name}%"), models.Quotation.terms_json.ilike(f"%{sm.name}%")),
            models.Quotation.created_at >= start_ms,
            models.Quotation.created_at <= end_ms
        ).all()
        
        sm_phones = {l.phone for l in sm_leads if l.phone}
        if sm_phones:
            q_by_phone = db.query(models.Quotation).filter(
                models.Quotation.customer_phone.in_(sm_phones),
                models.Quotation.created_at >= start_ms,
                models.Quotation.created_at <= end_ms
            ).all()
            seen_qids = {q.id for q in q_rows}
            for qp in q_by_phone:
                if qp.id not in seen_qids:
                    q_rows.append(qp)

        quotes_count = len(q_rows)
        approved_quotes = [q for q in q_rows if q.status in ["Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed"]]
        approved_count = len(approved_quotes)
        quote_value = sum(q.grand_total for q in q_rows)
        approved_val = sum(q.grand_total for q in approved_quotes)

        quote_ids = [q.id for q in q_rows]
        collected = 0.0
        if quote_ids:
            collected = db.query(func.coalesce(func.sum(models.Payment.amount), 0.0)).filter(
                models.Payment.quotation_id.in_(quote_ids),
                models.Payment.payment_date >= start_ms,
                models.Payment.payment_date <= end_ms
            ).scalar() or 0.0

        conversion_rate = round((converted_count / leads_count * 100.0), 1) if leads_count > 0 else 0.0

        salesman_metrics.append({
            "id": sm.id,
            "name": sm.name,
            "area": sm.area or "General",
            "leads": leads_count,
            "converted_customers": converted_count,
            "quotations": quotes_count,
            "approved_quotations": approved_count,
            "quotation_value": round(float(quote_value), 2),
            "approved_value": round(float(approved_val), 2),
            "payments_collected": round(float(collected), 2),
            "conversion_rate": conversion_rate
        })

    salesman_metrics.sort(key=lambda x: x["approved_value"], reverse=True)

    # Telecaller performance
    telecallers = db.query(models.Telecaller).filter(models.Telecaller.active == True).all()
    telecaller_metrics = []
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    for tc in telecallers:
        assigned_leads = db.query(models.Lead).filter(
            models.Lead.assigned_to == tc.name,
            models.Lead.created_at >= start_ms,
            models.Lead.created_at <= end_ms
        ).all()
        assigned_count = len(assigned_leads)
        converted_count = sum(1 for l in assigned_leads if l.status == "Converted")

        fu_query = db.query(models.LeadFollowup).filter(
            models.LeadFollowup.assigned_to == tc.name,
            models.LeadFollowup.created_at >= start_ms,
            models.LeadFollowup.created_at <= end_ms
        )
        total_fu = fu_query.count()
        completed_fu = fu_query.filter(models.LeadFollowup.status == "Completed").count()
        pending_fu = fu_query.filter(models.LeadFollowup.status == "Pending").count()
        overdue_fu = fu_query.filter(
            models.LeadFollowup.status == "Pending",
            models.LeadFollowup.follow_up_date != "",
            models.LeadFollowup.follow_up_date < today_str
        ).count()

        conv_rate = round((converted_count / assigned_count * 100.0), 1) if assigned_count > 0 else 0.0

        telecaller_metrics.append({
            "id": tc.id,
            "name": tc.name,
            "assigned_leads": assigned_count,
            "converted_leads": converted_count,
            "total_followups": total_fu,
            "completed_followups": completed_fu,
            "pending_followups": pending_fu,
            "overdue_followups": overdue_fu,
            "conversion_rate": conv_rate
        })

    telecaller_metrics.sort(key=lambda x: x["completed_followups"], reverse=True)

    return {
        "salesmen": salesman_metrics,
        "telecallers": telecaller_metrics
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. QUOTATION ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/quotations")
def get_quotation_analytics(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    query = db.query(models.Quotation).filter(models.Quotation.created_at >= start_ms, models.Quotation.created_at <= end_ms)
    if customer:
        query = query.filter(models.Quotation.customer_name == customer)
    if status and status != "All":
        query = query.filter(models.Quotation.status == status)

    quotes = query.all()
    total_quotes = len(quotes)

    status_counts: Dict[str, int] = {}
    status_values: Dict[str, float] = {}
    for q in quotes:
        st = q.status or "Draft"
        status_counts[st] = status_counts.get(st, 0) + 1
        status_values[st] = status_values.get(st, 0.0) + (q.grand_total or 0.0)

    approved_statuses = ["Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed"]
    approved_count = sum(status_counts.get(s, 0) for s in approved_statuses)
    approved_val = sum(status_values.get(s, 0.0) for s in approved_statuses)
    rejected_count = status_counts.get("Cancelled", 0)

    total_val = sum(q.grand_total or 0.0 for q in quotes)
    avg_val = round(total_val / total_quotes, 2) if total_quotes > 0 else 0.0
    max_val = max([q.grand_total or 0.0 for q in quotes], default=0.0)

    approval_rate = round((approved_count / total_quotes * 100.0), 1) if total_quotes > 0 else 0.0

    trend_dict: Dict[str, Dict[str, Any]] = {}
    for q in quotes:
        dt = datetime.datetime.fromtimestamp(q.created_at / 1000).strftime("%Y-%m-%d")
        if dt not in trend_dict:
            trend_dict[dt] = {"date": dt, "count": 0, "value": 0.0}
        trend_dict[dt]["count"] += 1
        trend_dict[dt]["value"] += (q.grand_total or 0.0)

    trend_list = sorted(trend_dict.values(), key=lambda x: x["date"])

    return {
        "total_quotations": total_quotes,
        "approved_quotations": approved_count,
        "rejected_quotations": rejected_count,
        "approval_rate": approval_rate,
        "total_quotation_value": round(float(total_val), 2),
        "approved_quotation_value": round(float(approved_val), 2),
        "average_quotation_value": avg_val,
        "highest_quotation_value": round(float(max_val), 2),
        "status_distribution": [{"label": k, "count": v, "value": round(status_values.get(k, 0.0), 2)} for k, v in status_counts.items()],
        "trend": trend_list
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. FINANCIAL & REVENUE ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/financials")
def get_financial_analytics(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    q_query = db.query(models.Quotation).filter(models.Quotation.created_at >= start_ms, models.Quotation.created_at <= end_ms)
    if customer:
        q_query = q_query.filter(models.Quotation.customer_name == customer)
    quotes = q_query.all()

    total_quote_val = sum(q.grand_total or 0.0 for q in quotes)
    approved_statuses = ["Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed"]
    approved_val = sum(q.grand_total or 0.0 for q in quotes if q.status in approved_statuses)
    total_discounts = sum(q.discount_amount or 0.0 for q in quotes)
    total_gst = sum(q.gst_amount or 0.0 for q in quotes)

    p_query = db.query(models.Payment).filter(models.Payment.payment_date >= start_ms, models.Payment.payment_date <= end_ms)
    payments = p_query.all()
    payment_received = sum(p.amount for p in payments)

    mode_dict: Dict[str, float] = {}
    for p in payments:
        mode = p.payment_mode or "Cash"
        mode_dict[mode] = mode_dict.get(mode, 0.0) + p.amount

    type_dict: Dict[str, float] = {}
    for p in payments:
        ptype = p.payment_type or "Full Payment"
        type_dict[ptype] = type_dict.get(ptype, 0.0) + p.amount

    trend_dict: Dict[str, float] = {}
    for p in payments:
        dt = datetime.datetime.fromtimestamp(p.payment_date / 1000).strftime("%Y-%m-%d")
        trend_dict[dt] = trend_dict.get(dt, 0.0) + p.amount

    collection_trend = [{"date": k, "amount": round(v, 2)} for k, v in sorted(trend_dict.items())]

    cust_map: Dict[str, Dict[str, Any]] = {}
    all_approved = db.query(models.Quotation).filter(
        models.Quotation.status.in_(approved_statuses)
    ).all()

    for q in all_approved:
        c_name = q.customer_name or "Unknown Customer"
        if c_name not in cust_map:
            cust_map[c_name] = {
                "customer_name": c_name,
                "phone": q.customer_phone or "",
                "city": q.customer_city or "",
                "total_orders": 0,
                "total_billed": 0.0,
                "total_paid": 0.0,
                "outstanding": 0.0
            }
        cust_map[c_name]["total_orders"] += 1
        cust_map[c_name]["total_billed"] += (q.grand_total or 0.0)

    all_payments = db.query(models.Payment).all()
    q_to_cust = {q.id: q.customer_name for q in all_approved}
    for p in all_payments:
        c_name = q_to_cust.get(p.quotation_id)
        if c_name and c_name in cust_map:
            cust_map[c_name]["total_paid"] += p.amount

    customer_outstanding = []
    for c_data in cust_map.values():
        c_data["outstanding"] = round(max(0.0, c_data["total_billed"] - c_data["total_paid"]), 2)
        c_data["total_billed"] = round(c_data["total_billed"], 2)
        c_data["total_paid"] = round(c_data["total_paid"], 2)
        if c_data["outstanding"] > 0:
            customer_outstanding.append(c_data)

    customer_outstanding.sort(key=lambda x: x["outstanding"], reverse=True)
    outstanding_total = sum(c["outstanding"] for c in customer_outstanding)

    return {
        "total_quotation_value": round(float(total_quote_val), 2),
        "approved_sales_value": round(float(approved_val), 2),
        "payment_received": round(float(payment_received), 2),
        "outstanding_total": round(float(outstanding_total), 2),
        "total_discounts": round(float(total_discounts), 2),
        "total_gst": round(float(total_gst), 2),
        "advance_payments_sum": round(float(type_dict.get("Advance", 0.0)), 2),
        "full_payments_sum": round(float(type_dict.get("Full Payment", 0.0) + type_dict.get("Final", 0.0)), 2),
        "payment_mode_distribution": [{"label": k, "value": round(v, 2)} for k, v in mode_dict.items()],
        "payment_type_distribution": [{"label": k, "value": round(v, 2)} for k, v in type_dict.items()],
        "collection_trend": collection_trend,
        "customer_outstanding": customer_outstanding[:50]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. CUSTOMER INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/customers")
def get_customer_analytics(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    total_customers = db.query(models.Customer).count()
    new_customers = db.query(models.Customer).filter(
        models.Customer.created_at >= start_ms,
        models.Customer.created_at <= end_ms
    ).count()

    all_quotes = db.query(models.Quotation).all()
    all_po = db.query(models.ProductionOrder).all()

    cust_stats: Dict[str, Dict[str, Any]] = {}
    for q in all_quotes:
        name = q.customer_name or "Unknown"
        if name not in cust_stats:
            cust_stats[name] = {
                "name": name,
                "phone": q.customer_phone or "",
                "city": q.customer_city or "",
                "quotation_count": 0,
                "quotation_value": 0.0,
                "approved_value": 0.0,
                "production_orders": 0,
                "paid_amount": 0.0
            }
        cust_stats[name]["quotation_count"] += 1
        cust_stats[name]["quotation_value"] += (q.grand_total or 0.0)
        if q.status in ["Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed"]:
            cust_stats[name]["approved_value"] += (q.grand_total or 0.0)

    for po in all_po:
        name = po.customer_name or "Unknown"
        if name in cust_stats:
            cust_stats[name]["production_orders"] += 1

    payments = db.query(models.Payment).all()
    q_to_cust = {q.id: q.customer_name for q in all_quotes}
    for p in payments:
        name = q_to_cust.get(p.quotation_id)
        if name and name in cust_stats:
            cust_stats[name]["paid_amount"] += p.amount

    customer_list = []
    for c in cust_stats.values():
        c["quotation_value"] = round(c["quotation_value"], 2)
        c["approved_value"] = round(c["approved_value"], 2)
        c["paid_amount"] = round(c["paid_amount"], 2)
        c["outstanding"] = round(max(0.0, c["approved_value"] - c["paid_amount"]), 2)
        customer_list.append(c)

    customer_list.sort(key=lambda x: x["approved_value"], reverse=True)

    customers_with_quotes = sum(1 for c in customer_list if c["quotation_count"] > 0)
    customers_with_po = sum(1 for c in customer_list if c["production_orders"] > 0)
    avg_order_val = round(sum(c["approved_value"] for c in customer_list) / len(customer_list), 2) if customer_list else 0.0

    return {
        "total_customers": total_customers,
        "new_customers": new_customers,
        "customers_with_quotes": customers_with_quotes,
        "customers_with_production_orders": customers_with_po,
        "average_customer_order_value": avg_order_val,
        "top_customers": customer_list[:50]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 9. PRODUCT ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/products")
def get_product_analytics(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    quotes = db.query(models.Quotation).filter(
        models.Quotation.created_at >= start_ms,
        models.Quotation.created_at <= end_ms
    ).all()

    prod_map: Dict[str, Dict[str, Any]] = {}

    for q in quotes:
        is_approved = q.status in ["Approved", "Advance Paid", "Production", "Ready for Delivery", "Completed"]
        if not q.items_json:
            continue
        try:
            items = json.loads(q.items_json)
        except Exception:
            items = []

        for item in items:
            p_name = (item.get("name") or "Custom Item").strip()
            qty = float(item.get("qty", item.get("quantity", 1)))
            price = float(item.get("price", item.get("rate", 0)))
            total = qty * price

            if p_name not in prod_map:
                prod_map[p_name] = {
                    "product_name": p_name,
                    "category": item.get("category", "General"),
                    "quotations_count": 0,
                    "units_quoted": 0.0,
                    "units_approved": 0.0,
                    "production_units": 0.0,
                    "revenue": 0.0
                }

            prod_map[p_name]["quotations_count"] += 1
            prod_map[p_name]["units_quoted"] += qty
            if is_approved:
                prod_map[p_name]["units_approved"] += qty
                prod_map[p_name]["revenue"] += total

    po_items = db.query(models.ProductionItem).join(
        models.ProductionOrder, models.ProductionOrder.id == models.ProductionItem.production_order_id
    ).filter(
        models.ProductionOrder.created_at >= start_ms,
        models.ProductionOrder.created_at <= end_ms
    ).all()

    for pi in po_items:
        p_name = (pi.product_name or "").strip()
        if p_name in prod_map:
            prod_map[p_name]["production_units"] += (pi.quantity or 0.0)

    product_list = list(prod_map.values())
    for p in product_list:
        p["revenue"] = round(p["revenue"], 2)

    product_list.sort(key=lambda x: x["revenue"], reverse=True)

    return {
        "total_distinct_products": len(product_list),
        "products": product_list[:50]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 10. FACTORY, PRODUCTION & MATERIAL BOTTLENECK ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/factory")
def get_factory_analytics(
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    salesman: Optional[str] = None,
    db: Session = Depends(get_db)
):
    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    po_query = db.query(models.ProductionOrder).filter(
        models.ProductionOrder.created_at >= start_ms,
        models.ProductionOrder.created_at <= end_ms
    )
    if salesman:
        po_query = po_query.filter(models.ProductionOrder.sales_person == salesman)

    orders = po_query.all()
    total_orders = len(orders)

    status_counts: Dict[str, int] = {}
    completed_orders = []
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    delayed_orders = 0

    for o in orders:
        st = o.status or "Accepted"
        status_counts[st] = status_counts.get(st, 0) + 1
        if st in ["Completed", "Ready for Dispatch", "Dispatched"]:
            completed_orders.append(o)
        if o.expected_dispatch and o.expected_dispatch < today_str and st not in ["Completed", "Ready for Dispatch", "Dispatched", "Cancelled", "Rejected"]:
            delayed_orders += 1

    completion_rate = round((len(completed_orders) / total_orders * 100.0), 1) if total_orders > 0 else 0.0

    durations_hours = []
    for o in completed_orders:
        if o.updated_at and o.created_at and o.updated_at > o.created_at:
            durations_hours.append((o.updated_at - o.created_at) / (1000 * 3600))

    avg_duration_days = round((sum(durations_hours) / len(durations_hours) / 24.0), 1) if durations_hours else 0.0

    order_ids = [o.id for o in orders]
    mat_summary = {
        "total_requirements": 0,
        "total_required_qty": 0.0,
        "total_prepared_qty": 0.0,
        "total_remaining_qty": 0.0,
        "completed_count": 0,
        "pending_count": 0,
        "completion_rate": 0.0
    }
    top_materials: Dict[str, Dict[str, Any]] = {}

    if order_ids:
        reqs = db.query(models.ProductionMaterialRequirement).filter(
            models.ProductionMaterialRequirement.production_order_id.in_(order_ids)
        ).all()

        mat_summary["total_requirements"] = len(reqs)
        for r in reqs:
            req_qty = float(r.required_qty or 0.0)
            prep_qty = float(r.prepared_qty or 0.0)
            rem_qty = max(0.0, req_qty - prep_qty)

            mat_summary["total_required_qty"] += req_qty
            mat_summary["total_prepared_qty"] += prep_qty
            mat_summary["total_remaining_qty"] += rem_qty

            if r.manufacturing_status == "Completed":
                mat_summary["completed_count"] += 1
            else:
                mat_summary["pending_count"] += 1

            m_name = (r.material_name or "General Material").strip()
            if m_name not in top_materials:
                top_materials[m_name] = {
                    "material_name": m_name,
                    "unit": r.unit or "Pcs",
                    "required_qty": 0.0,
                    "prepared_qty": 0.0,
                    "remaining_qty": 0.0,
                    "orders_count": 0
                }
            top_materials[m_name]["required_qty"] += req_qty
            top_materials[m_name]["prepared_qty"] += prep_qty
            top_materials[m_name]["remaining_qty"] += rem_qty
            top_materials[m_name]["orders_count"] += 1

        if mat_summary["total_required_qty"] > 0:
            mat_summary["completion_rate"] = round(
                (mat_summary["total_prepared_qty"] / mat_summary["total_required_qty"] * 100.0), 1
            )

    mat_summary["total_required_qty"] = round(mat_summary["total_required_qty"], 2)
    mat_summary["total_prepared_qty"] = round(mat_summary["total_prepared_qty"], 2)
    mat_summary["total_remaining_qty"] = round(mat_summary["total_remaining_qty"], 2)

    material_bottlenecks = list(top_materials.values())
    material_bottlenecks.sort(key=lambda x: x["remaining_qty"], reverse=True)

    return {
        "total_production_orders": total_orders,
        "completed_orders": len(completed_orders),
        "delayed_orders": delayed_orders,
        "completion_rate": completion_rate,
        "average_production_days": avg_duration_days,
        "status_distribution": [{"label": k, "count": v} for k, v in status_counts.items()],
        "materials": mat_summary,
        "material_bottlenecks": material_bottlenecks[:20]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 11. UNIFIED LIVE ACTIVITY FEED
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/activity")
def get_recent_activity(limit: int = Query(25, ge=5, le=100), db: Session = Depends(get_db)):
    """
    Returns real recent activities across CRM, quotations, payments, and factory floor.
    """
    activities = []

    l_acts = db.query(models.LeadActivity).order_by(models.LeadActivity.created_at.desc()).limit(limit).all()
    for a in l_acts:
        activities.append({
            "id": a.id,
            "category": "CRM",
            "action": a.action,
            "entity": f"Lead #{a.lead_number}",
            "user": a.username or a.role or "Staff",
            "details": f"{a.action}: {a.new_value}" if a.new_value else a.action,
            "timestamp": a.created_at
        })

    payments = db.query(models.Payment).order_by(models.Payment.payment_date.desc()).limit(limit).all()
    for p in payments:
        activities.append({
            "id": p.id,
            "category": "Payment",
            "action": f"Payment Received (₹{p.amount:,.2f})",
            "entity": f"Invoice {p.invoice_number}",
            "user": p.created_by or "Admin",
            "details": f"Mode: {p.payment_mode}, Type: {p.payment_type}",
            "timestamp": p.payment_date
        })

    quotes = db.query(models.Quotation).order_by(models.Quotation.created_at.desc()).limit(limit).all()
    for q in quotes:
        activities.append({
            "id": q.id,
            "category": "Quotation",
            "action": f"Quotation {q.status}",
            "entity": f"{q.quote_number} ({q.customer_name})",
            "user": "Sales / Admin",
            "details": f"Grand Total: ₹{q.grand_total:,.2f}",
            "timestamp": q.created_at
        })

    p_stages = db.query(models.ProductionStatusHistory).order_by(models.ProductionStatusHistory.created_at.desc()).limit(limit).all()
    for s in p_stages:
        activities.append({
            "id": s.id,
            "category": "Factory",
            "action": f"Stage {s.stage_name} {s.status}",
            "entity": "Production Floor",
            "user": s.completed_by or "Factory Staff",
            "details": s.remarks or f"Stage updated to {s.status}",
            "timestamp": s.created_at
        })

    activities.sort(key=lambda x: x["timestamp"], reverse=True)
    return activities[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# 12. EXPORT CSV
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export")
def export_analytics_csv(
    report_type: str = Query("kpis", description="kpis | sales | customers | factory | materials"),
    period: str = Query("month"),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Exports tabular analytics data to CSV format safely."""
    output = io.StringIO()
    writer = csv.writer(output)

    start_ms, end_ms, _, _ = resolve_date_ranges(period, date_from, date_to)

    if report_type == "sales":
        sales_data = get_sales_performance(period, date_from, date_to, None, db)
        writer.writerow(["Salesman", "Area", "Leads", "Converted", "Quotations", "Approved Quotes", "Quote Value", "Approved Value", "Collected", "Conv Rate %"])
        for s in sales_data["salesmen"]:
            writer.writerow([s["name"], s["area"], s["leads"], s["converted_customers"], s["quotations"], s["approved_quotations"], s["quotation_value"], s["approved_value"], s["payments_collected"], s["conversion_rate"]])
        filename = f"sales_performance_{period}.csv"

    elif report_type == "customers":
        cust_data = get_customer_analytics(period, date_from, date_to, db)
        writer.writerow(["Customer Name", "Phone", "City", "Quotes Count", "Approved Value", "Paid Amount", "Outstanding Balance", "Production Orders"])
        for c in cust_data["top_customers"]:
            writer.writerow([c["name"], c["phone"], c["city"], c["quotation_count"], c["approved_value"], c["paid_amount"], c["outstanding"], c["production_orders"]])
        filename = f"customers_analytics_{period}.csv"

    elif report_type == "materials":
        factory_data = get_factory_analytics(period, date_from, date_to, None, db)
        writer.writerow(["Material Name", "Unit", "Required Qty", "Prepared Qty", "Remaining Qty", "Orders Count"])
        for m in factory_data["material_bottlenecks"]:
            writer.writerow([m["material_name"], m["unit"], m["required_qty"], m["prepared_qty"], m["remaining_qty"], m["orders_count"]])
        filename = f"material_bottlenecks_{period}.csv"

    else:
        overview = get_analytics_overview(period, date_from, date_to, None, None, None, None, None, db)
        writer.writerow(["Metric", "Current Value", "Previous Value", "Change %"])
        for k, v in overview["kpis"].items():
            writer.writerow([k, v["value"], v["previous"], f"{v['change_pct']}%"])
        filename = f"business_kpis_{period}.csv"

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
