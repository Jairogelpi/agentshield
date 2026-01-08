from fastapi import APIRouter, Depends, HTTPException, Header, Query
from typing import Optional, List, Dict, Any
from app.db import supabase, redis_client
from app.db import supabase, redis_client
from app.routers.authorize import get_tenant_from_jwt as get_current_tenant_id # Alias for safely
import json
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import io
import csv
import secrets
import hashlib
from app.services.pricing_sync import sync_prices_from_openrouter

router = APIRouter(prefix="/v1/dashboard", tags=["Dashboard"])

# Helper rápido para política (si no quieres refactorizar authorize.py)
def get_policy_rules(tenant_id: str):
    # Intentar caché
    cache_key = f"policy:active:{tenant_id}"
    cached = redis_client.get(cache_key)
    if cached: return json.loads(cached)
    
    # DB fallback
    res = supabase.table("policies").select("rules").eq("tenant_id", tenant_id).eq("is_active", True).execute()
    if res.data: return res.data[0]['rules']
    return {}

@router.get("/summary")
async def get_summary(
    tenant_id: str = Depends(get_current_tenant_id),
    cost_center_id: Optional[str] = Query(None, description="Filtrar por centro de coste específico")
):
    # Lógica Dinámica:
    # Si viene cost_center, damos detalle. Si no, damos TOTAL de la empresa.
    
    current_spend = 0.0
    
    if cost_center_id:
        spend_key = f"spend:{tenant_id}:{cost_center_id}"
        current_spend = float(redis_client.get(spend_key) or 0.0)
    else:
        # Calcular TOTAL (Sumar todos los cost centers)
        # 1. Intentar key de "total_spend" en Redis si la tuvieras
        # 2. O consultar DB (Source of Truth) para sumar todos
        res = supabase.table("cost_centers").select("current_spend").eq("tenant_id", tenant_id).execute()
        if res.data:
            current_spend = sum(float(item['current_spend']) for item in res.data)
            
    # Leer límite (La política define el límite Global o del CC?)
    # Asumimos que la política define el límite MENSUAL GLOBAL del Tenant.
    policy = get_policy_rules(tenant_id)
    monthly_limit = policy.get("limits", {}).get("monthly", 0)
    
    return {
        "scope": cost_center_id or "GLOBAL",
        "current_spend": current_spend,
        "monthly_limit": monthly_limit,
        "percent": round((current_spend / monthly_limit * 100), 1) if monthly_limit > 0 else 0
    }

@router.get("/receipts")
async def get_receipts(tenant_id: str = Depends(get_current_tenant_id)):
    # Traer últimos 10 recibos
    res = supabase.table("receipts").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).limit(10).execute()
    return res.data
    return res.data

# --- SaaS Control Endpoints ---

class UpdatePolicyRequest(BaseModel):
    rules: Dict[str, Any]

@router.get("/policy")
async def get_policy_config(tenant_id: str = Depends(get_current_tenant_id)):
    """Devuelve la configuración JSON completa para pre-llenar el formulario del UI."""
    # Reutilizamos tu helper get_policy_rules o leemos directo de DB
    res = supabase.table("policies").select("rules, mode").eq("tenant_id", tenant_id).eq("is_active", True).single().execute()
    
    if not res.data:
        # Política por defecto si es nueva cuenta
        return {
            "mode": "active",
            "limits": {"monthly": 0, "per_request": 0},
            "allowlist": {"models": []},
            "governance": {"require_approval_above_cost": 0}
        }
        
    rules = res.data['rules']
    # Mezclamos el campo 'mode' que a veces está fuera del JSON de reglas
    rules['mode'] = res.data.get('mode', 'active') 
    return rules

@router.put("/policy")
async def update_policy(
    update_req: UpdatePolicyRequest, 
    tenant_id: str = Depends(get_current_tenant_id)
):
    """
    Permite al cliente cambiar sus límites (autonomía).
    """
    # 1. Actualizar en Base de Datos (Source of Truth)
    supabase.table("policies")\
        .update({"rules": update_req.rules})\
        .eq("tenant_id", tenant_id)\
        .eq("is_active", True)\
        .execute()
        
    # 2. CRÍTICO: Invalidar Caché de Redis
    redis_client.delete(f"policy:active:{tenant_id}")
    
    return {"status": "updated", "message": "Policy cache cleared and DB updated."}

class UpdateWebhookRequest(BaseModel):
    url: str
    events: List[str] = ["authorization.denied"] # Eventos por defecto

@router.put("/webhook")
async def update_webhook(
    req: UpdateWebhookRequest,
    tenant_id: str = Depends(get_current_tenant_id)
):
    """
    Configura la URL para recibir alertas en tiempo real.
    """
    # Upsert (Insertar o Actualizar) la configuración del webhook
    # Requiere que la tabla 'webhooks' tenga una restricción UNIQUE en tenant_id
    supabase.table("webhooks").upsert({
        "tenant_id": tenant_id,
        "url": req.url,
        "events": req.events,
        "is_active": True,
        "updated_at": "now()"
    }, on_conflict="tenant_id").execute()
    
    return {"status": "updated", "message": "Webhook configuration saved."}

# --- Enterprise Control Endpoints ---

@router.post("/admin/sync-prices")
async def trigger_price_sync(
    x_admin_secret: str = Header(None)
):
    """
    Endpoint de mantenimiento para actualizar precios desde OpenRouter.
    """
    result = await sync_prices_from_openrouter()
    return result

# --- BUSINESS LOGIC (MARGINS & AUDITS) ---

@router.get("/analytics/profitability")
async def get_profitability_report(
    tenant_id: str = Depends(get_current_tenant_id),
    start_date: str = Query(None), # YYYY-MM-DD
    end_date: str = Query(None)
):
    """
    Calcula la rentabilidad real: Coste vs Facturable (Markup).
    """
    # 1. Fetch Tenant Config (Default Markup)
    tenant_res = supabase.table("tenants").select("default_markup").eq("id", tenant_id).single().execute()
    default_markup = float(tenant_res.data.get("default_markup") or 1.0)
    
    # 2. Fetch Cost Centers (Overrides)
    cc_res = supabase.table("cost_centers").select("name, markup").eq("tenant_id", tenant_id).execute()
    cc_map = {cc["name"]: float(cc["markup"]) for cc in cc_res.data if cc["markup"]}
    
    # 3. Fetch Receipts (Aggregation)
    # En producción real, esto debería ser una RPC o View
    query = supabase.table("receipts").select("cost_center_id, cost").eq("tenant_id", tenant_id)
    if start_date: query = query.gte("created_at", f"{start_date}T00:00:00")
    if end_date: query = query.lte("created_at", f"{end_date}T23:59:59")
    
    data = query.execute().data
    
    # 4. Calculate Logic
    total_cost = 0.0
    total_billable = 0.0
    breakdown = {}
    
    for r in data:
        cc_name = r.get("cost_center_id") or "Unassigned"
        cost = float(r.get("cost") or 0.0)
        
        # Determine Markup
        markup = cc_map.get(cc_name, default_markup)
        billable = cost * markup
        
        total_cost += cost
        total_billable += billable
        
        if cc_name not in breakdown:
            breakdown[cc_name] = {"cost": 0.0, "billable": 0.0, "markup_used": markup}
        
        breakdown[cc_name]["cost"] += cost
        breakdown[cc_name]["billable"] += billable

    gross_margin = total_billable - total_cost
    margin_percent = (gross_margin / total_billable * 100) if total_billable > 0 else 0.0
    
    return {
        "period": {"start": start_date, "end": end_date},
        "financials": {
            "total_cost_internal": round(total_cost, 4),
            "total_billable_client": round(total_billable, 4),
            "gross_margin_value": round(gross_margin, 4),
            "gross_margin_percent": round(margin_percent, 2)
        },
        "breakdown_by_project": breakdown
        "breakdown_by_project": breakdown
    }

@router.get("/analytics/history")
async def get_spending_history(
    tenant_id: str = Depends(get_current_tenant_id),
    days: int = 30
):
    """Devuelve datos agregados por día para pintar el gráfico principal."""
    import datetime
    
    # Calcular fecha de corte
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    
    res = supabase.table("receipts").select("created_at, cost_real").eq("tenant_id", tenant_id).gte("created_at", cutoff).execute()
    
    # Agregación en memoria (Rápida en Python para volúmenes medios)
    daily_stats = {}
    
    for r in res.data:
        day = r['created_at'][:10] # YYYY-MM-DD
        daily_stats[day] = daily_stats.get(day, 0.0) + float(r['cost_real'])
        
    # Formato lista ordenada para Recharts/Chart.js
    chart_data = [{"date": k, "amount": round(v, 4)} for k, v in sorted(daily_stats.items())]
    
    return chart_data

@router.get("/reports/audit", response_class=StreamingResponse)
async def download_dispute_pack(
    tenant_id: str = Depends(get_current_tenant_id),
    month: str = Query(None) # YYYY-MM
):
    """
    Genera el 'Dispute Pack': CSV con evidencia criptográfica para clientes.
    """
    # Fetch data
    query = supabase.table("receipts").select("*").eq("tenant_id", tenant_id)
    # Filtro de fecha simple...
    
    data = query.execute().data
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header Clean (Business Friendly)
    writer.writerow(["Date", "Project / Cost Center", "User / Actor", "Model", "Task", "Tokens", "Cost (EUR)", "Signature (Proof)"])
    
    for r in data:
        meta = r.get("metadata") or {}
        usage = meta.get("usage_data") or {}
        
        writer.writerow([
            r.get("created_at"),
            r.get("cost_center_id"),
            meta.get("user_metadata", {}).get("user_id") or "System",
            meta.get("model"),
            meta.get("user_metadata", {}).get("task_type") or "General",
            usage.get("total_tokens", 0),
            f"{r.get('cost', 0):.4f}",
            "VERIFIED_SHA256_RSA" # Aquí iría el hash si lo guardáramos en columna dedicada, o partial del ID
        ])
        
    output.seek(0)
    
    response = StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv"
    )
    response.headers["Content-Disposition"] = "attachment; filename=agentshield_audit_pack.csv"
    return response

@router.post("/emergency/stop")
async def kill_switch(tenant_id: str = Depends(get_current_tenant_id)):
    """
    Botón del Pánico: Detiene todo el tráfico de IA inmediatamente.
    """
    # Sobrescribimos la política activa con límites a CERO
    panic_rules = {
        "limits": {"monthly": 0, "per_request": 0},
        "allowlist": {"providers": [], "models": []},
        "panic_mode": True
    }
    
    # 1. Actualizar DB
    try:
        supabase.table("policies").update({"rules": panic_rules}).eq("tenant_id", tenant_id).eq("is_active", True).execute()
    except Exception as e:
        # Si falla DB, intentar Redis (que es lo critico)
        pass

    # 2. Borrar Caché (Efecto inmediato)
    redis_client.delete(f"policy:active:{tenant_id}")
    # También forzar un flag de bloqueo
    redis_client.set(f"kill_switch:{tenant_id}", "block", ex=3600*24)
    
    return {"status": "STOPPED", "message": "EMERGENCY STOP ACTIVATED. All requests will be denied."}

@router.get("/export/csv")
async def export_receipts_csv(tenant_id: str = Depends(get_current_tenant_id)):
    """
    Genera un CSV descargable con todas las transacciones.
    """
    # Obtener datos (Limitado a 1000 para MVP)
    res = supabase.table("receipts").select("*").eq("tenant_id", tenant_id).order("created_at", desc=True).limit(1000).execute()
    data = res.data
    
    # Crear CSV en memoria
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Cabeceras
    writer.writerow(["Receipt ID", "Date", "Cost Center", "Provider", "Model", "Cost (EUR)", "Status"])
    
    # Filas
    for row in data:
        # Extraer metadatos de JSON si es necesario
        # Safely get nested dicts
        usage = row.get("usage_data") or {}
        if isinstance(usage, str): # En caso de que venga como string JSON
             try: usage = json.loads(usage)
             except: usage = {}
             
        model = usage.get("model", "unknown")
        provider = usage.get("provider", "unknown")
        
        writer.writerow([
            row.get("id"),
            row.get("created_at"),
            row.get("cost_center_id"),
            provider,
            model,
            row.get("cost_real"),
            "VERIFIED"
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agentshield_report.csv"}
    )

@router.post("/keys/rotate")
async def rotate_api_key(
    tenant_id: str = Depends(get_current_tenant_id)
):
    # 1. Generar nueva key
    raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    
    # 2. Hashear para guardar
    hashed = hashlib.sha256(raw_key.encode()).hexdigest()
    
    # 3. Update DB
    supabase.table("tenants").update({"api_key_hash": hashed}).eq("id", tenant_id).execute()
    
    return {
        "new_api_key": raw_key,
        "message": "Copy this key NOW. You won't see it again."
    }

@router.get("/analytics/top-spenders")
async def get_top_spenders(tenant_id: str = Depends(get_current_tenant_id)):
    """
    Desglosa el gasto por Modelo. 
    Ayuda al cliente a saber quién se está comiendo el presupuesto.
    """
    # Simulación para MVP (en producción usa SQL Group By con RPC)
    # Traemos últimos 500 recibos para hacer estadística rápida
    receipts = supabase.table("receipts").select("usage_data, cost_real").eq("tenant_id", tenant_id).limit(500).execute()
    
    by_model = {}
    total_analyzed = 0.0
    
    for r in receipts.data:
        # Extraer metadatos de forma segura
        usage = r.get("usage_data") or {}
        if isinstance(usage, str): 
             try: usage = json.loads(usage)
             except: usage = {}
             
        model = usage.get("model", "unknown")
        cost = r.get("cost_real", 0.0)
        
        by_model[model] = by_model.get(model, 0) + cost
        total_analyzed += cost
        
    # Ordenar por gasto (Mayor a menor)
    sorted_models = dict(sorted(by_model.items(), key=lambda item: item[1], reverse=True))
        
    return {
        "by_model": sorted_models,
        "sample_size": len(receipts.data),
        "total_in_sample": total_analyzed
    }

# --- COST CENTER MANAGEMENT (COMPLETE) ---

class CostCenterConfig(BaseModel):
    name: str
    markup: Optional[float] = None
    monthly_limit: float = 0.0
    is_billable: bool = True
    hard_limit_daily: Optional[float] = None

@router.get("/cost-centers")
async def list_cost_centers(tenant_id: str = Depends(get_current_tenant_id)):
    """Lista todos los proyectos y su configuración actual."""
    res = supabase.table("cost_centers").select("*").eq("tenant_id", tenant_id).execute()
    return res.data

@router.post("/cost-centers")
async def create_cost_center(
    config: CostCenterConfig, 
    tenant_id: str = Depends(get_current_tenant_id)
):
    """Crea un nuevo proyecto (ej: 'Marketing Coca-Cola') con sus reglas."""
    # Nota: El ID se autogenera gracias al patch SQL que aplicamos
    data = {
        "tenant_id": tenant_id,
        "name": config.name,
        "markup": config.markup,
        "monthly_limit": config.monthly_limit,
        "is_billable": config.is_billable,
        "hard_limit_daily": config.hard_limit_daily
    }
    try:
        res = supabase.table("cost_centers").insert(data).execute()
        return {"status": "created", "data": res.data[0]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error creating Cost Center: {str(e)}")

@router.put("/cost-centers/{cc_id}")
async def update_cost_center(
    cc_id: str, 
    config: CostCenterConfig, 
    tenant_id: str = Depends(get_current_tenant_id)
):
    """Edita las reglas de facturación de un proyecto en tiempo real."""
    data = {
        "name": config.name,
        "markup": config.markup,
        "monthly_limit": config.monthly_limit,
        "is_billable": config.is_billable,
        "hard_limit_daily": config.hard_limit_daily
    }
    
    # Actualizar DB
    supabase.table("cost_centers").update(data).eq("id", cc_id).eq("tenant_id", tenant_id).execute()
    
    # CRÍTICO: Invalidar Caché de Gasto para que el nuevo límite aplique ya
    redis_client.delete(f"spend:{tenant_id}:{cc_id}")
    
    return {"status": "updated", "message": "Project configuration updated"}

@router.delete("/cost-centers/{cc_id}")
async def delete_cost_center(cc_id: str, tenant_id: str = Depends(get_current_tenant_id)):
    """Elimina un proyecto (Solo si no tiene recibos asociados por FK constraints)."""
    try:
        supabase.table("cost_centers").delete().eq("id", cc_id).eq("tenant_id", tenant_id).execute()
        return {"status": "deleted"}
    except Exception:
        raise HTTPException(status_code=400, detail="Cannot delete project with active receipts. Archive it instead.")

# --- TENANT SETTINGS (NEW) ---

class TenantSettings(BaseModel):
    name: Optional[str] = None
    default_markup: Optional[float] = None
    is_active: Optional[bool] = None

@router.get("/settings")
async def get_tenant_settings(tenant_id: str = Depends(get_current_tenant_id)):
    """Ver configuración global de la agencia."""
    res = supabase.table("tenants").select("name, default_markup, is_active, created_at").eq("id", tenant_id).single().execute()
    return res.data

@router.put("/settings")
async def update_tenant_settings(
    settings: TenantSettings, 
    tenant_id: str = Depends(get_current_tenant_id)
):
    """Cambiar el nombre de la agencia o su margen por defecto."""
    updates = {}
    if settings.name is not None: updates["name"] = settings.name
    if settings.default_markup is not None: updates["default_markup"] = settings.default_markup
    # is_active no lo dejamos cambiar aquí para que no se auto-bloqueen por error
    
    if not updates:
        return {"status": "no_changes"}

    supabase.table("tenants").update(updates).eq("id", tenant_id).execute()
    
    return {"status": "updated", "data": updates}

# --- HUMAN-IN-THE-LOOP (APPROVALS) ---

class ApprovalDecision(BaseModel):
    decision: str # APPROVED, DENIED
    reason: Optional[str] = None

@router.get("/approvals")
async def list_pending_approvals(tenant_id: str = Depends(get_current_tenant_id)):
    """Lista solicitudes que requieren aprobación humana."""
    res = supabase.table("authorizations")\
        .select("*")\
        .eq("tenant_id", tenant_id)\
        .eq("decision", "PENDING_APPROVAL")\
        .order("created_at", desc=True)\
        .execute()
    return res.data

@router.post("/approvals/{auth_id}/decision")
async def resolve_approval(
    auth_id: str, 
    decision_body: ApprovalDecision,
    tenant_id: str = Depends(get_current_tenant_id)
):
    """
    El Manager aprueba o rechaza la solicitud.
    Si APRUEBA, el agente (que está haciendo polling) verá el cambio y continuará.
    """
    if decision_body.decision not in ["APPROVED", "DENIED"]:
        raise HTTPException(status_code=400, detail="Decision must be APPROVED or DENIED")
        
    res = supabase.table("authorizations").update({
        "decision": decision_body.decision,
        "reason_code": decision_body.reason or f"Manual decision by Manager",
        # Opcional: guardar ID del manager que aprobó si lo tuviéramos
    }).eq("id", auth_id).eq("tenant_id", tenant_id).execute()
    
    return {"status": "resolved", "data": res.data}

# --- CUSTOM PRICING (NEW) ---

class CustomPrice(BaseModel):
    model_name: str # Ej: "scraper-v1" o "my-local-llama"
    price_per_unit: float # Ej: 0.002
    unit_type: str = "request" # request, token, minute

@router.post("/prices/custom")
async def set_custom_price(
    price: CustomPrice,
    tenant_id: str = Depends(get_current_tenant_id)
):
    """Permite a la agencia definir costes para herramientas que no son LLMs públicos."""
    # Guardamos esto en la tabla model_prices
    # OJO: Para evitar colisiones con precios oficiales, podemos usar un prefijo o un provider custom.
    
    data = {
        "provider": f"custom-{tenant_id}", # Namespace seguro por tenant
        "model": price.model_name,
        "price_in": price.price_per_unit, # Usamos price_in como precio base unitario
        "price_out": 0,
        "is_active": True,
        "updated_at": "now()"
    }
    
    try:
        supabase.table("model_prices").upsert(data, on_conflict="provider, model").execute()
        # Invalidar caché
        redis_client.delete(f"price:{price.model_name}")
        return {"status": "ok", "message": f"Price for {price.model_name} set to {price.price_per_unit}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


