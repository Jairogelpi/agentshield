# agentshield_core/app/routers/dashboard.py
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from typing import Optional, List, Dict, Any
from app.db import supabase, redis_client
from app.routers.authorize import get_tenant_from_jwt as get_current_tenant_id
import json
import os
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import io
import csv
import secrets
import hashlib
from app.services.pricing_sync import sync_prices_from_openrouter
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

router = APIRouter(prefix="/v1/dashboard", tags=["Dashboard"])

# Helper rápido para política
async def get_policy_rules(tenant_id: str):
    cache_key = f"policy:active:{tenant_id}"
    cached = await redis_client.get(cache_key)
    if cached: return json.loads(cached)
    res = supabase.table("policies").select("rules").eq("tenant_id", tenant_id).eq("is_active", True).execute()
    if res.data: return res.data[0]['rules']
    return {}

@router.get("/summary")
async def get_summary(
    tenant_id: str = Depends(get_current_tenant_id),
    cost_center_id: Optional[str] = Query(None, description="Filtrar por centro de coste específico")
):
    current_spend = 0.0
    if cost_center_id:
        spend_key = f"spend:{tenant_id}:{cost_center_id}"
        current_spend = float(await redis_client.get(spend_key) or 0.0)
    else:
        res = supabase.table("cost_centers").select("current_spend").eq("tenant_id", tenant_id).execute()
        if res.data:
            current_spend = sum(float(item['current_spend']) for item in res.data)
            
    policy = await get_policy_rules(tenant_id)
    monthly_limit = policy.get("limits", {}).get("monthly", 0)
    
    return {
        "scope": cost_center_id or "GLOBAL",
        "current_spend": current_spend,
        "monthly_limit": monthly_limit,
        "percent": round((current_spend / monthly_limit * 100), 1) if monthly_limit > 0 else 0
    }

@router.get("/receipts")
async def get_receipts(tenant_id: str = Depends(get_current_tenant_id)):
    res = supabase.table("receipts") \
        .select("id, created_at, cost_real, cost_center_id, cache_hit, tokens_saved") \
        .eq("tenant_id", tenant_id) \
        .order("created_at", desc=True) \
        .limit(10) \
        .execute()
    return res.data

class UpdatePolicyRequest(BaseModel):
    rules: Dict[str, Any]

@router.get("/policy")
async def get_policy_config(tenant_id: str = Depends(get_current_tenant_id)):
    res = supabase.table("policies").select("rules, mode").eq("tenant_id", tenant_id).eq("is_active", True).single().execute()
    if not res.data:
        return {"mode": "active", "limits": {"monthly": 0, "per_request": 0}, "allowlist": {"models": []}, "governance": {"require_approval_above_cost": 0}}
    rules = res.data['rules']
    rules['mode'] = res.data.get('mode', 'active') 
    return rules

@router.put("/policy")
async def update_policy(update_req: UpdatePolicyRequest, tenant_id: str = Depends(get_current_tenant_id)):
    supabase.table("policies").update({"rules": update_req.rules}).eq("tenant_id", tenant_id).eq("is_active", True).execute()
    await redis_client.delete(f"policy:active:{tenant_id}")
    return {"status": "updated", "message": "Policy cache cleared and DB updated."}

class UpdateWebhookRequest(BaseModel):
    url: str
    events: List[str] = ["authorization.denied"]

@router.put("/webhook")
async def update_webhook(req: UpdateWebhookRequest, tenant_id: str = Depends(get_current_tenant_id)):
    supabase.table("webhooks").upsert({
        "tenant_id": tenant_id, "url": req.url, "events": req.events, "is_active": True, "updated_at": "now()"
    }, on_conflict="tenant_id").execute()
    return {"status": "updated", "message": "Webhook configuration saved."}

# --- ADMIN ENDPOINT (CORREGIDO) ---
@router.post("/admin/sync-prices")
async def trigger_price_sync(x_admin_secret: str = Header(None)):
    """
    Endpoint de mantenimiento. AHORA PROTEGIDO.
    """
    # 1. Verificar Seguridad
    env_secret = os.getenv("ADMIN_SECRET_KEY")
    if not env_secret or x_admin_secret != env_secret:
        raise HTTPException(status_code=403, detail="Unauthorized Admin Access")

    # 2. Ejecutar
    result = await sync_prices_from_openrouter()
    return result

@router.get("/analytics/profitability")
async def get_profitability_report(tenant_id: str = Depends(get_current_tenant_id), start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None)):
    try:
        rpc_params = {
            "p_tenant_id": tenant_id,
            "p_start_date": f"{start_date}T00:00:00" if start_date else None,
            "p_end_date": f"{end_date}T23:59:59" if end_date else None
        }
        res = supabase.rpc("get_tenant_profitability", rpc_params).execute()
        data = res.data
        total_cost = sum(item['total_cost'] for item in data)
        total_billable = sum(item['total_billable'] for item in data)
        gross_margin = total_billable - total_cost
        return {
            "period": {"start": start_date, "end": end_date},
            "financials": {
                "total_cost_internal": round(total_cost, 4),
                "total_billable_client": round(total_billable, 4),
                "gross_margin_value": round(gross_margin, 4),
                "gross_margin_percent": round((gross_margin / total_billable * 100), 2) if total_billable > 0 else 0
            },
            "breakdown_by_project": {item['cost_center_id']: {"cost": round(item['total_cost'], 4), "billable": round(item['total_billable'], 4), "margin": round(item['margin_value'], 4)} for item in data}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en reporte: {str(e)}")

@router.get("/analytics/history")
async def get_spending_history(tenant_id: str = Depends(get_current_tenant_id), days: int = 30):
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    res = supabase.table("receipts").select("created_at, cost_real").eq("tenant_id", tenant_id).gte("created_at", cutoff).execute()
    daily_stats = {}
    for r in res.data:
        day = r['created_at'][:10]
        daily_stats[day] = daily_stats.get(day, 0.0) + float(r['cost_real'])
    chart_data = [{"date": k, "amount": round(v, 4)} for k, v in sorted(daily_stats.items())]
    return chart_data

@router.get("/reports/audit", response_class=StreamingResponse)
async def download_dispute_pack(tenant_id: str = Depends(get_current_tenant_id), month: str = Query(None)):
    with tracer.start_as_current_span("export_dispute_pack") as span:
        span.set_attribute("tenant.id", tenant_id)
        query = supabase.table("receipts").select("created_at, cost_center_id, usage_data, cost_real, signature, processed_in").eq("tenant_id", tenant_id)
        data = query.execute().data
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Project", "Model", "Cost (EUR)", "Region", "Cryptographic Proof (JWS Signature)"])
        for r in data:
            meta = r.get("usage_data") or {}
            writer.writerow([r.get("created_at"), r.get("cost_center_id"), meta.get("model", "N/A"), f"{r.get('cost_real', 0):.6f}", r.get("processed_in", "eu"), r.get("signature")])
        output.seek(0)
        return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=agentshield_audit_pack.csv"})

@router.post("/emergency/stop")
async def kill_switch(tenant_id: str = Depends(get_current_tenant_id)):
    panic_rules = {"limits": {"monthly": 0, "per_request": 0}, "allowlist": {"providers": [], "models": []}, "panic_mode": True}
    try: supabase.table("policies").update({"rules": panic_rules}).eq("tenant_id", tenant_id).eq("is_active", True).execute()
    except Exception: pass
    await redis_client.delete(f"policy:active:{tenant_id}")
    await redis_client.set(f"kill_switch:{tenant_id}", "block", ex=3600*24)
    return {"status": "STOPPED", "message": "EMERGENCY STOP ACTIVATED."}

@router.get("/export/csv")
async def export_receipts_csv(tenant_id: str = Depends(get_current_tenant_id)):
    res = supabase.table("receipts").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).limit(1000).execute()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Receipt ID", "Date", "Cost Center", "Provider", "Model", "Cost (EUR)", "Status"])
    for row in res.data:
        usage = row.get("usage_data") or {}
        if isinstance(usage, str): 
             try: usage = json.loads(usage)
             except: usage = {}
        writer.writerow([row.get("id"), row.get("created_at"), row.get("cost_center_id"), usage.get("provider", "unknown"), usage.get("model", "unknown"), row.get("cost_real"), "VERIFIED"])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=agentshield_report.csv"})

@router.post("/keys/rotate")
async def rotate_api_key(tenant_id: str = Depends(get_current_tenant_id)):
    raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    supabase.table("tenants").update({"api_key_hash": hashed}).eq("id", tenant_id).execute()
    return {"new_api_key": raw_key, "message": "Copy this key NOW."}

@router.get("/analytics/top-spenders")
async def get_top_spenders(tenant_id: str = Depends(get_current_tenant_id)):
    receipts = supabase.table("receipts").select("usage_data, cost_real").eq("tenant_id", tenant_id).limit(500).execute()
    by_model = {}
    total = 0.0
    for r in receipts.data:
        usage = r.get("usage_data") or {}
        if isinstance(usage, str): 
             try: usage = json.loads(usage)
             except: usage = {}
        model = usage.get("model", "unknown")
        cost = r.get("cost_real", 0.0)
        by_model[model] = by_model.get(model, 0) + cost
        total += cost
    return {"by_model": dict(sorted(by_model.items(), key=lambda x: x[1], reverse=True)), "sample_size": len(receipts.data), "total_in_sample": total}

class CostCenterConfig(BaseModel):
    name: str
    markup: Optional[float] = None
    monthly_limit: float = 0.0
    is_billable: bool = True
    hard_limit_daily: Optional[float] = None

@router.get("/cost-centers")
async def list_cost_centers(tenant_id: str = Depends(get_current_tenant_id)):
    return supabase.table("cost_centers").select("*").eq("tenant_id", tenant_id).execute().data

@router.post("/cost-centers")
async def create_cost_center(config: CostCenterConfig, tenant_id: str = Depends(get_current_tenant_id)):
    data = {"tenant_id": tenant_id, "name": config.name, "markup": config.markup, "monthly_limit": config.monthly_limit, "is_billable": config.is_billable, "hard_limit_daily": config.hard_limit_daily}
    try:
        res = supabase.table("cost_centers").insert(data).execute()
        return {"status": "created", "data": res.data[0]}
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))

@router.put("/cost-centers/{cc_id}")
async def update_cost_center(cc_id: str, config: CostCenterConfig, tenant_id: str = Depends(get_current_tenant_id)):
    data = {"name": config.name, "markup": config.markup, "monthly_limit": config.monthly_limit, "is_billable": config.is_billable, "hard_limit_daily": config.hard_limit_daily}
    supabase.table("cost_centers").update(data).eq("id", cc_id).eq("tenant_id", tenant_id).execute()
    await redis_client.delete(f"spend:{tenant_id}:{cc_id}")
    return {"status": "updated", "message": "Project configuration updated"}

@router.delete("/cost-centers/{cc_id}")
async def delete_cost_center(cc_id: str, tenant_id: str = Depends(get_current_tenant_id)):
    try:
        supabase.table("cost_centers").delete().eq("id", cc_id).eq("tenant_id", tenant_id).execute()
        return {"status": "deleted"}
    except: raise HTTPException(status_code=400, detail="Cannot delete project with active receipts.")

class TenantSettings(BaseModel):
    name: Optional[str] = None
    default_markup: Optional[float] = None
    is_active: Optional[bool] = None

@router.get("/settings")
async def get_tenant_settings(tenant_id: str = Depends(get_current_tenant_id)):
    res = supabase.table("tenants").select("name, default_markup, is_active, created_at").eq("id", tenant_id).single().execute()
    return res.data

@router.put("/settings")
async def update_tenant_settings(settings: TenantSettings, tenant_id: str = Depends(get_current_tenant_id)):
    updates = {k: v for k, v in settings.dict().items() if v is not None}
    if not updates: return {"status": "no_changes"}
    supabase.table("tenants").update(updates).eq("id", tenant_id).execute()
    return {"status": "updated", "data": updates}

class ApprovalDecision(BaseModel):
    decision: str
    reason: Optional[str] = None

@router.get("/approvals")
async def list_pending_approvals(tenant_id: str = Depends(get_current_tenant_id)):
    res = supabase.table("authorizations").select("*").eq("tenant_id", tenant_id).eq("decision", "PENDING_APPROVAL").order("created_at", desc=True).execute()
    return res.data

@router.post("/approvals/{auth_id}/decision")
async def resolve_approval(auth_id: str, decision_body: ApprovalDecision, tenant_id: str = Depends(get_current_tenant_id)):
    if decision_body.decision not in ["APPROVED", "DENIED"]: raise HTTPException(status_code=400, detail="Invalid Decision")
    res = supabase.table("authorizations").update({"decision": decision_body.decision, "reason_code": decision_body.reason or "Manual decision"}).eq("id", auth_id).eq("tenant_id", tenant_id).execute()
    return {"status": "resolved", "data": res.data}

class CustomPrice(BaseModel):
    model_name: str
    price_per_unit: float
    unit_type: str = "request"

@router.post("/prices/custom")
async def set_custom_price(price: CustomPrice, tenant_id: str = Depends(get_current_tenant_id)):
    data = {"provider": f"custom-{tenant_id}", "model": price.model_name, "price_in": price.price_per_unit, "price_out": 0, "is_active": True, "updated_at": "now()"}
    supabase.table("model_prices").upsert(data, on_conflict="provider, model").execute()
    await redis_client.delete(f"price:{price.model_name}")
    return {"status": "ok", "message": f"Price set for {price.model_name}"}

@router.get("/traces/{trace_id}/full")
async def get_full_trace_story(trace_id: str, tenant_id: str = Depends(get_current_tenant_id)):
    # Nota: ilike es lento, pero funcional para MVP.
    res = supabase.table("receipts").select("*").eq("tenant_id", tenant_id).ilike("usage_data::text", f"%{trace_id}%").execute()
    if not res.data: raise HTTPException(status_code=404, detail="Trace not found")
    total_latency = sum(float(r.get('usage_data', {}).get('latency_ms', 0)) for r in res.data)
    total_cost = sum(float(r.get('cost_real', 0)) for r in res.data)
    return {"summary": {"trace_id": trace_id, "total_latency_ms": round(total_latency, 2), "total_cost": round(total_cost, 6), "steps_count": len(res.data)}, "timeline": res.data}

@router.get("/compliance/residency-report")
async def get_residency_report(tenant_id: str = Depends(get_current_tenant_id)):
    res = supabase.table("receipts").select("processed_in").eq("tenant_id", tenant_id).execute()
    eu_count = sum(1 for r in res.data if r.get('processed_in') == 'eu')
    us_count = sum(1 for r in res.data if r.get('processed_in') == 'us')
    compliance_status = "CRITICAL_ERROR" if (eu_count > 0 and us_count > 0) else "COMPLIANT"
    return {"total_requests": len(res.data), "processed_in_eu": eu_count, "processed_in_us": us_count, "compliance_percentage": 100.0 if compliance_status == "COMPLIANT" else 0.0}

@router.get("/audit/transactions")
async def get_transaction_audit_log(tenant_id: str = Depends(get_current_tenant_id), limit: int = 50):
    """
    Financial Audit Endpoint (Double Write Verification).
    Muestra el log inmutable de intentos de cobro, útil para conciliar si Redis falla.
    """
    res = supabase.table("pending_transactions_log")\
        .select("*")\
        .eq("tenant_id", tenant_id)\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    return res.data

@router.get("/market/health")
async def get_market_health_matrix(tenant_id: str = Depends(get_current_tenant_id)):
    """
    Scientific Arbitrage Dashboard.
    Muestra qué modelos están 'calientes' (baja latencia/volatilidad) y cuáles están penalizados.
    Data source: Filtro de Kalman en Redis (Real-time).
    """
    # 1. Obtener modelos activos
    res = supabase.table("model_prices").select("model, provider").eq("is_active", True).execute()
    models = res.data
    
    health_matrix = []
    for m in models:
        model_id = m['model']
        # Recuperar estado del Filtro de Kalman
        lat_x = await redis_client.get(f"stats:latency:{model_id}:x")
        vol_p = await redis_client.get(f"stats:latency:{model_id}:p")
        
        # Interpretación
        latency_est = float(lat_x) if lat_x else 0.0
        uncertainty = float(vol_p) if vol_p else 0.0
        
        status = "HEALTHY"
        if latency_est > 2000: status = "DEGRADED"
        if uncertainty > 5.0: status = "VOLATILE"
        
        health_matrix.append({
            "model": model_id,
            "provider": m['provider'],
            "estimated_latency_ms": round(latency_est, 1),
            "volatility_index": round(uncertainty, 2), # < 1.0 es muy estable
            "status": status
        })
        
    # Ordenar por latencia (los mejores primero)
    return sorted(health_matrix, key=lambda x: x["estimated_latency_ms"])
