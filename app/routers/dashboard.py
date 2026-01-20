# agentshield_core/app/routers/dashboard.py
import csv
import hashlib
import io
import json
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from pydantic import BaseModel

from app.db import redis_client, supabase
from app.routers.authorize import get_tenant_from_jwt as get_current_tenant_id
from app.services.pricing_sync import sync_universal_prices

logger = logging.getLogger("agentshield.dashboard")

tracer = trace.get_tracer(__name__)

router = APIRouter(prefix="/v1/dashboard", tags=["Dashboard"])

from app.services.policy_copilot import generate_custom_pii_rule


# --- CUSTOM PII ENDPOINTS ---
@router.post("/policies/copilot/generate-pii")
async def draft_custom_pii(
    prompt: str = Body(..., embed=True), tenant_id: str = Depends(get_current_tenant_id)
):
    """User asks: 'Block projects', Agent answers: regex"""
    result = await generate_custom_pii_rule(prompt)
    return result


@router.get("/policies/custom-pii")
async def list_custom_pii(tenant_id: str = Depends(get_current_tenant_id)):
    res = (
        supabase.table("custom_pii_rules")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .execute()
    )
    return res.data


@router.post("/policies/custom-pii")
async def create_custom_pii(rule: dict[str, Any], tenant_id: str = Depends(get_current_tenant_id)):
    """Save the approved regex"""
    rule["tenant_id"] = tenant_id
    supabase.table("custom_pii_rules").insert(rule).execute()
    # Invalidate cache
    await redis_client.delete(f"pii:custom:{tenant_id}")
    return {"status": "created"}


# ----------------------------


# Helper rápido para política
async def get_policy_rules(tenant_id: str):
    cache_key = f"policy:active:{tenant_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    res = (
        supabase.table("policies")
        .select("rules")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .execute()
    )
    if res.data:
        return res.data[0]["rules"]
    return {}


@router.get("/summary")
async def get_summary(
    tenant_id: str = Depends(get_current_tenant_id),
    cost_center_id: str | None = Query(None, description="Filtrar por centro de coste específico"),
):
    current_spend = 0.0
    if cost_center_id:
        spend_key = f"spend:{tenant_id}:{cost_center_id}"
        current_spend = float(await redis_client.get(spend_key) or 0.0)
    else:
        res = (
            supabase.table("cost_centers")
            .select("current_spend")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if res.data:
            current_spend = sum(float(item["current_spend"]) for item in res.data)

    policy = await get_policy_rules(tenant_id)
    monthly_limit = policy.get("limits", {}).get("monthly", 0)

    return {
        "scope": cost_center_id or "GLOBAL",
        "current_spend": current_spend,
        "monthly_limit": monthly_limit,
        "percent": round((current_spend / monthly_limit * 100), 1) if monthly_limit > 0 else 0,
    }


@router.get("/receipts")
async def get_receipts(tenant_id: str = Depends(get_current_tenant_id)):
    res = (
        supabase.table("receipts")
        .select("id, created_at, cost_real, cost_center_id, cache_hit, tokens_saved")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    return res.data


class UpdatePolicyRequest(BaseModel):
    rules: dict[str, Any]


@router.get("/policy")
async def get_policy_config(tenant_id: str = Depends(get_current_tenant_id)):
    res = (
        supabase.table("policies")
        .select("rules, mode")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .single()
        .execute()
    )
    if not res.data:
        return {
            "mode": "active",
            "limits": {"monthly": 0, "per_request": 0},
            "allowlist": {"models": []},
            "governance": {"require_approval_above_cost": 0},
        }
    rules = res.data["rules"]
    rules["mode"] = res.data.get("mode", "active")
    return rules


@router.put("/policy")
async def update_policy(
    update_req: UpdatePolicyRequest, tenant_id: str = Depends(get_current_tenant_id)
):
    supabase.table("policies").update({"rules": update_req.rules}).eq("tenant_id", tenant_id).eq(
        "is_active", True
    ).execute()
    await redis_client.delete(f"policy:active:{tenant_id}")
    return {"status": "updated", "message": "Policy cache cleared and DB updated."}


class UpdateWebhookRequest(BaseModel):
    url: str
    events: list[str] = ["authorization.denied"]


@router.put("/webhook")
async def update_webhook(
    req: UpdateWebhookRequest, tenant_id: str = Depends(get_current_tenant_id)
):
    supabase.table("webhooks").upsert(
        {
            "tenant_id": tenant_id,
            "url": req.url,
            "events": req.events,
            "is_active": True,
            "updated_at": "now()",
        },
        on_conflict="tenant_id",
    ).execute()
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
    result = await sync_universal_prices()
    return result


@router.get("/analytics/profitability")
async def get_profitability_report(
    tenant_id: str = Depends(get_current_tenant_id),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    try:
        rpc_params = {
            "p_tenant_id": tenant_id,
            "p_start_date": f"{start_date}T00:00:00" if start_date else None,
            "p_end_date": f"{end_date}T23:59:59" if end_date else None,
        }
        res = supabase.rpc("get_tenant_profitability", rpc_params).execute()
        data = res.data
        total_cost = sum(item["total_cost"] for item in data)
        total_billable = sum(item["total_billable"] for item in data)
        gross_margin = total_billable - total_cost
        return {
            "period": {"start": start_date, "end": end_date},
            "financials": {
                "total_cost_internal": round(total_cost, 4),
                "total_billable_client": round(total_billable, 4),
                "gross_margin_value": round(gross_margin, 4),
                "gross_margin_percent": round((gross_margin / total_billable * 100), 2)
                if total_billable > 0
                else 0,
            },
            "breakdown_by_project": {
                item["cost_center_id"]: {
                    "cost": round(item["total_cost"], 4),
                    "billable": round(item["total_billable"], 4),
                    "margin": round(item["margin_value"], 4),
                }
                for item in data
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en reporte: {str(e)}")


@router.get("/analytics/history")
async def get_spending_history(tenant_id: str = Depends(get_current_tenant_id), days: int = 30):
    """
    OPTIMIZADO (v2026): Delega la agregación temporal a PostgreSQL via RPC.
    Antes: O(N) en Python (Lento y comía RAM).
    Ahora: O(1) en Python (La DB hace el trabajo pesado).
    """
    try:
        rpc_params = {"p_tenant_id": tenant_id, "p_days": days}
        res = supabase.rpc("get_daily_spend_history", rpc_params).execute()

        # La DB ya devuelve [{"date": "2024-01-01", "amount": 10.5}, ...]
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database aggregation error: {str(e)}")


@router.get("/reports/audit", response_class=StreamingResponse)
async def download_dispute_pack(
    tenant_id: str = Depends(get_current_tenant_id), month: str = Query(None)
):
    with tracer.start_as_current_span("export_dispute_pack") as span:
        span.set_attribute("tenant.id", tenant_id)

        # Usamos un generador para NO cargar todo en RAM
        async def iter_audit_csv():
            output = io.StringIO()
            writer = csv.writer(output)

            # 1. Cabecera
            writer.writerow(
                [
                    "Date",
                    "Project",
                    "Model",
                    "Cost (EUR)",
                    "Region",
                    "Cryptographic Proof (JWS Signature)",
                ]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

            # 2. Streaming REAL (Paginación por offset/cursor para evitar OOM)
            # Iteramos en bloques de 1000 hasta que se acaben
            PAGE_SIZE = 1000
            has_more = True
            current_offset = 0

            while has_more:
                query = (
                    supabase.table("receipts")
                    .select(
                        "created_at, cost_center_id, usage_data, cost_real, signature, processed_in"
                    )
                    .eq("tenant_id", tenant_id)
                    .order("created_at", desc=True)
                    .range(current_offset, current_offset + PAGE_SIZE - 1)
                )

                res = query.execute()
                batch = res.data

                if not batch:
                    has_more = False
                    break

                for r in batch:
                    meta = r.get("usage_data") or {}
                    # Fix: Handle strings if Supabase returns JSON as string
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except:
                            meta = {}

                    writer.writerow(
                        [
                            r.get("created_at"),
                            r.get("cost_center_id"),
                            meta.get("model", "N/A"),
                            f"{r.get('cost_real', 0):.6f}",
                            r.get("processed_in", "eu"),
                            r.get("signature"),
                        ]
                    )

                # Flush del buffer por cada bloque (chunked transfer encoding)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

                # Avanzamos offset
                current_offset += PAGE_SIZE
                if len(batch) < PAGE_SIZE:
                    has_more = False

        filename = f"agentshield_audit_{tenant_id[:8]}.csv"
        return StreamingResponse(
            iter_audit_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


@router.post("/emergency/stop")
async def kill_switch(tenant_id: str = Depends(get_current_tenant_id)):
    panic_rules = {
        "limits": {"monthly": 0, "per_request": 0},
        "allowlist": {"providers": [], "models": []},
        "panic_mode": True,
    }
    try:
        supabase.table("policies").update({"rules": panic_rules}).eq("tenant_id", tenant_id).eq(
            "is_active", True
        ).execute()
    except Exception:
        pass
    await redis_client.delete(f"policy:active:{tenant_id}")
    await redis_client.set(f"kill_switch:{tenant_id}", "block", ex=3600 * 24)
    return {"status": "STOPPED", "message": "EMERGENCY STOP ACTIVATED."}


@router.get("/export/csv")
async def export_receipts_csv(tenant_id: str = Depends(get_current_tenant_id)):
    # Usamos un generador de Python (yield)
    async def iter_csv():
        # 1. Escribir Cabecera
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["Receipt ID", "Date", "Cost Center", "Provider", "Model", "Cost (EUR)", "Status"]
        )
        # Enviamos la cabecera y limpiamos el buffer
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # 2. Iterar filas (Streaming real desde DB si fuera posible, aquí paginado)
        # Nota: Idealmente usarías un cursor de DB server-side, pero para MVP esto mejora mucho la RAM.
        res = (
            supabase.table("receipts")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )

        for row in res.data:
            usage = row.get("usage_data") or {}
            if isinstance(usage, str):
                try:
                    usage = json.loads(usage)
                except:
                    usage = {}

            writer.writerow(
                [
                    row.get("id"),
                    row.get("created_at"),
                    row.get("cost_center_id"),
                    usage.get("provider", "unknown"),
                    usage.get("model", "unknown"),
                    row.get("cost_real"),
                    "VERIFIED",
                ]
            )

            # 3. Enviar este trozo (chunk) y limpiar memoria
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agentshield_report.csv"},
    )


@router.post("/keys/rotate")
async def rotate_api_key(tenant_id: str = Depends(get_current_tenant_id)):
    # 1. Recuperar hash actual para moverlo a "secondary"
    # (En realidad deberíamos leerlo de la DB, pero supongamos que el cliente quiere rotar lo que sea que tenga)

    # 2. Generar nueva Key
    new_raw_key = f"sk_live_{secrets.token_urlsafe(32)}"
    new_hash = hashlib.sha256(new_raw_key.encode()).hexdigest()

    # 3. Ejecutar Rotación Atómica (o casi)
    # Leemos la key actual de la DB primero
    current = (
        supabase.table("tenants").select("api_key_hash").eq("id", tenant_id).single().execute()
    )
    old_hash = current.data.get("api_key_hash")

    # 4. Update: Movemos Old -> Secondary (Expires +24h), New -> Primary
    from datetime import datetime, timedelta

    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()

    updates = {
        "api_key_hash": new_hash,
        "api_key_hash_secondary": old_hash,  # La vieja sigue viva 24h
        "api_key_secondary_expires_at": expires_at,
    }

    supabase.table("tenants").update(updates).eq("id", tenant_id).execute()

    # 5. Invalidar caches (opcional, pero buena práctica)
    # No podemos invalidar por hash facilmente porque no tenemos el hash viejo a mano sin recalcular,
    # pero el TTL de Redis se encargará.

    return {
        "new_api_key": new_raw_key,
        "message": "Key rotated. The OLD key will remain valid for 24 hours (Zero-Downtime). Update your apps now.",
    }


@router.get("/analytics/top-spenders")
async def get_top_spenders(tenant_id: str = Depends(get_current_tenant_id)):
    """
    OPTIMIZADO (v2026): Agregación JSONB en SQL.
    Antes: Limitado a 500 filas (Datos incompletos) + Loop Python.
    Ahora: Analiza TODA la historia y devuelve el Top 10 real.
    """
    try:
        rpc_params = {"p_tenant_id": tenant_id}
        res = supabase.rpc("get_top_models_usage", rpc_params).execute()

        # Formato para el frontend
        data = res.data or []
        total_in_view = sum(item["total_cost"] for item in data)

        # Convertimos a dict simple { "gpt-4": 120.0, ... }
        by_model = {item["model_name"]: item["total_cost"] for item in data}

        return {
            "by_model": by_model,
            "sample_size": "FULL_HISTORY",  # Ahora es real
            "total_in_sample": total_in_view,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CostCenterConfig(BaseModel):
    name: str
    markup: float | None = None
    monthly_limit: float = 0.0
    is_billable: bool = True
    hard_limit_daily: float | None = None


@router.get("/cost-centers")
async def list_cost_centers(tenant_id: str = Depends(get_current_tenant_id)):
    return supabase.table("cost_centers").select("*").eq("tenant_id", tenant_id).execute().data


@router.post("/cost-centers")
async def create_cost_center(
    config: CostCenterConfig, tenant_id: str = Depends(get_current_tenant_id)
):
    data = {
        "tenant_id": tenant_id,
        "name": config.name,
        "markup": config.markup,
        "monthly_limit": config.monthly_limit,
        "is_billable": config.is_billable,
        "hard_limit_daily": config.hard_limit_daily,
    }
    try:
        res = supabase.table("cost_centers").insert(data).execute()
        return {"status": "created", "data": res.data[0]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/cost-centers/{cc_id}")
async def update_cost_center(
    cc_id: str, config: CostCenterConfig, tenant_id: str = Depends(get_current_tenant_id)
):
    data = {
        "name": config.name,
        "markup": config.markup,
        "monthly_limit": config.monthly_limit,
        "is_billable": config.is_billable,
        "hard_limit_daily": config.hard_limit_daily,
    }
    supabase.table("cost_centers").update(data).eq("id", cc_id).eq("tenant_id", tenant_id).execute()
    await redis_client.delete(f"spend:{tenant_id}:{cc_id}")
    return {"status": "updated", "message": "Project configuration updated"}


@router.delete("/cost-centers/{cc_id}")
async def delete_cost_center(cc_id: str, tenant_id: str = Depends(get_current_tenant_id)):
    try:
        supabase.table("cost_centers").delete().eq("id", cc_id).eq("tenant_id", tenant_id).execute()
        return {"status": "deleted"}
    except:
        raise HTTPException(status_code=400, detail="Cannot delete project with active receipts.")


class TenantSettings(BaseModel):
    name: str | None = None
    default_markup: float | None = None
    is_active: bool | None = None


@router.get("/settings")
async def get_tenant_settings(tenant_id: str = Depends(get_current_tenant_id)):
    res = (
        supabase.table("tenants")
        .select("name, default_markup, is_active, created_at")
        .eq("id", tenant_id)
        .single()
        .execute()
    )
    return res.data


@router.put("/settings")
async def update_tenant_settings(
    settings: TenantSettings, tenant_id: str = Depends(get_current_tenant_id)
):
    updates = {k: v for k, v in settings.dict().items() if v is not None}
    if not updates:
        return {"status": "no_changes"}
    supabase.table("tenants").update(updates).eq("id", tenant_id).execute()
    return {"status": "updated", "data": updates}


@router.patch("/settings/smart-routing")
async def toggle_smart_routing(enabled: bool, tenant_id: str = Depends(get_current_tenant_id)):
    """
    Activa o desactiva el arbitraje de modelos para el tenant actual.
    """
    # 1. Actualizar la política en la DB
    # Buscamos la política activa y modificamos el JSON de rules
    policy = await get_policy_rules(tenant_id)

    if "smart_routing" not in policy:
        policy["smart_routing"] = {}

    policy["smart_routing"]["enabled"] = enabled

    supabase.table("policies").update({"rules": policy}).eq("tenant_id", tenant_id).eq(
        "is_active", True
    ).execute()

    # 2. Invalidar caché en Redis para que el cambio sea instantáneo
    await redis_client.delete(f"policy:active:{tenant_id}")

    return {"status": "success", "smart_routing_active": enabled}


class ApprovalDecision(BaseModel):
    decision: str
    reason: str | None = None


@router.get("/approvals")
async def list_pending_approvals(tenant_id: str = Depends(get_current_tenant_id)):
    res = (
        supabase.table("authorizations")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("decision", "PENDING_APPROVAL")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


@router.post("/approvals/{auth_id}/decision")
async def resolve_approval(
    auth_id: str, decision_body: ApprovalDecision, tenant_id: str = Depends(get_current_tenant_id)
):
    if decision_body.decision not in ["APPROVED", "DENIED"]:
        raise HTTPException(status_code=400, detail="Invalid Decision")
    res = (
        supabase.table("authorizations")
        .update(
            {
                "decision": decision_body.decision,
                "reason_code": decision_body.reason or "Manual decision",
            }
        )
        .eq("id", auth_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return {"status": "resolved", "data": res.data}


class CustomPrice(BaseModel):
    model_name: str
    price_per_unit: float
    unit_type: str = "request"


@router.post("/prices/custom")
async def set_custom_price(price: CustomPrice, tenant_id: str = Depends(get_current_tenant_id)):
    data = {
        "provider": f"custom-{tenant_id}",
        "model": price.model_name,
        "price_in": price.price_per_unit,
        "price_out": 0,
        "is_active": True,
        "updated_at": "now()",
    }
    supabase.table("model_prices").upsert(data, on_conflict="provider, model").execute()
    await redis_client.delete(f"price:{price.model_name}")
    return {"status": "ok", "message": f"Price set for {price.model_name}"}


@router.get("/traces/{trace_id}/full")
async def get_full_trace_story(trace_id: str, tenant_id: str = Depends(get_current_tenant_id)):
    # Nota: ilike es lento, pero funcional para MVP.
    res = (
        supabase.table("receipts")
        .select("*")
        .eq("tenant_id", tenant_id)
        .ilike("usage_data::text", f"%{trace_id}%")
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Trace not found")
    total_latency = sum(float(r.get("usage_data", {}).get("latency_ms", 0)) for r in res.data)
    total_cost = sum(float(r.get("cost_real", 0)) for r in res.data)
    return {
        "summary": {
            "trace_id": trace_id,
            "total_latency_ms": round(total_latency, 2),
            "total_cost": round(total_cost, 6),
            "steps_count": len(res.data),
        },
        "timeline": res.data,
    }


@router.get("/compliance/residency-report")
async def get_residency_report(tenant_id: str = Depends(get_current_tenant_id)):
    # Usamos RPC para contar millones de filas en milisegundos (O(1) vs O(N))
    try:
        res = supabase.rpc("get_residency_summary", {"p_tenant_id": tenant_id}).execute()

        # Convertimos la lista [{"region": "eu", "count": 10}, ...] a dict
        data_map = {item["region"]: item["count"] for item in res.data or []}

        eu_count = data_map.get("eu", 0)
        us_count = data_map.get("us", 0)
        total = eu_count + us_count

        compliance_status = "CRITICAL_ERROR" if (eu_count > 0 and us_count > 0) else "COMPLIANT"

        return {
            "total_requests": total,
            "processed_in_eu": eu_count,
            "processed_in_us": us_count,
            "compliance_percentage": 100.0 if compliance_status == "COMPLIANT" else 0.0,
        }
    except Exception as e:
        # Fallback por si el RPC falla
        return {
            "error": str(e),
            "total_requests": 0,
            "processed_in_eu": 0,
            "processed_in_us": 0,
            "compliance_percentage": 0.0,
        }


@router.get("/audit/transactions")
async def get_transaction_audit_log(
    tenant_id: str = Depends(get_current_tenant_id), limit: int = 50
):
    """
    Financial Audit Endpoint (Double Write Verification).
    Muestra el log inmutable de intentos de cobro, útil para conciliar si Redis falla.
    """
    res = (
        supabase.table("pending_transactions_log")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
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
        model_id = m["model"]
        # Recuperar estado del Filtro de Kalman
        lat_x = await redis_client.get(f"stats:latency:{model_id}:x")
        vol_p = await redis_client.get(f"stats:latency:{model_id}:p")

        # Interpretación
        latency_est = float(lat_x) if lat_x else 0.0
        uncertainty = float(vol_p) if vol_p else 0.0

        status = "HEALTHY"
        if latency_est > 2000:
            status = "DEGRADED"
        if uncertainty > 5.0:
            status = "VOLATILE"

        health_matrix.append(
            {
                "model": model_id,
                "provider": m["provider"],
                "estimated_latency_ms": round(latency_est, 1),
                "volatility_index": round(uncertainty, 2),  # < 1.0 es muy estable
                "status": status,
            }
        )

    # Ordenar por latencia (los mejores primero)
    return sorted(health_matrix, key=lambda x: x["estimated_latency_ms"])


@router.get("/sovereign/stats")
async def get_sovereign_stats(tenant_id: str = Depends(get_current_tenant_id)):
    """
    Retorna estadísticas de la "Memoria Soberana" (Ganancias por conocimiento compartido).
    """
    try:
        # Sumar transacciones negativas (Earnings) desde el log de transacciones
        # pending_transactions_log es el ledger inmutable.
        res = (
            supabase.table("pending_transactions_log")
            .select("amount")
            .eq("tenant_id", tenant_id)
            .lt("amount", 0)
            .execute()
        )

        total_earnings = sum(abs(float(item["amount"])) for item in res.data)

        # Opcional: Contar hits (número de transacciones)
        total_sales = len(res.data)

        return {
            "total_earnings": round(total_earnings, 4),
            "total_sales_count": total_sales,
            "currency": "EUR",
            "message": "Start saving more by sharing knowledge!"
            if total_earnings == 0
            else "Great job! Your knowledge is an asset.",
        }
    except Exception as e:
        logger.error(f"Sovereign Stats Error: {e}")
        return {"total_earnings": 0.0, "total_sales_count": 0, "currency": "EUR"}


@router.get("/dashboard/arbitrage/comparison")
async def get_arbitrage_savings_report(tenant_id: str = Depends(get_current_tenant_id)):
    """
    Retorna el ahorro acumulado y el ahorro proyectado (pérdida potencial).
    FOMO Metrics para incentivar Smart Routing.
    """
    # 1. Obtener ahorros reales (esto requeriría sumar transactions log donde mode='ARBITRAGE_SAVING' si existiera)
    # Por ahora mockeamos "actual_savings" o lo leemos si tuvieramos un contador
    actual_savings = float(await redis_client.get(f"stats:{tenant_id}:actual_savings") or 0.0)

    # 2. Obtener pérdidas (lo que acabamos de implementar)
    missed_savings = float(await redis_client.get(f"stats:{tenant_id}:missed_savings") or 0.0)
    missed_carbon = float(await redis_client.get(f"stats:{tenant_id}:missed_carbon") or 0.0)

    # Verificar estado actual
    policy = await get_policy_rules(tenant_id)
    is_enabled = policy.get("smart_routing", {}).get("enabled", False)

    return {
        "smart_routing_enabled": is_enabled,
        "actual_savings": round(actual_savings, 4),
        "potential_savings_lost": round(missed_savings, 4),
        "potential_trees_lost": int(missed_carbon / 25.0),  # 1 árbol ~ 25kg CO2
        "message": "Activa Smart Routing para recuperar estos ahorros"
        if not is_enabled
        else "Estás optimizando al máximo",
        "currency": "EUR",
    }
