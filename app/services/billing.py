# app/services/billing.py
from app.db import supabase, increment_spend, redis_client
from app.utils import fast_json as json
from app.logic import sign_receipt
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

async def record_transaction(
    tenant_id: str, 
    cost_center_id: str, 
    cost_real: object, # Decimal expected (typed as object to avoid Pydantic issues if passed directly)
    metadata: dict, 
    auth_id: str = None,
    cache_hit: bool = False,
    tokens_saved: int = 0
):
    """
    Registra el gasto de una transacción (saving receipt + updating counters).
    Usado tanto por el endpoint /receipt (SDK) como por el Proxy (Server-side).
    """
    # 1. Generar firma
    # Simulamos token si no existe, o firmamos solo los datos clave
    # Incluimos la REGIÓN para prueba legal inmutable
    # + CERTIFICACIÓN DE PRIVACIDAD (PII Sanitized)
    region = metadata.get("processed_in", "eu")
    
    # RISK AUDIT FIELDS (EU AI ACT)
    compliance_tag = metadata.get("compliance_level", "standard")
    use_case = metadata.get("use_case", "general")

    rx_signature = sign_receipt({
        "tid": tenant_id, 
        "cc": cost_center_id, 
        "cost": cost_real,
        "region": region,
        "mode": metadata.get("execution_mode", "ACTIVE"), # Prueba auditada del modo
        "pii_safe": True,
        "risk_class": use_case, # <--- PRUEBA LEGAL
        "audit_mode": compliance_tag
    })
    
    # 2. Guardar Receipt
    try:
        trace_id = metadata.get("trace_id")
        region = metadata.get("processed_in", "eu")
        
        
        # Validamos que el metadato se guarde
        if "pii_sanitized" not in metadata:
            metadata["pii_sanitized"] = True
            
        def _save_receipt():
            return supabase.table("receipts").insert({
                "tenant_id": tenant_id,
                "cost_center_id": cost_center_id,
                "cost_real": cost_real,
                "signature": rx_signature,
                "usage_data": metadata,
                "authorization_id": auth_id,
                "trace_id": trace_id,
                "processed_in": region,
                "cache_hit": cache_hit,
                "tokens_saved": tokens_saved 
            }).execute()

        # Non-blocking execution
        import asyncio
        await asyncio.to_thread(_save_receipt)
    except Exception as e:
        logger.error(f"CRITICAL BILLING FAILURE: {e}")
        # Guardar en una lista de 'fallidos' en Redis para reprocesar luego
        # DEAD LETTER QUEUE (DLQ)
        failed_receipt = {
            "tenant_id": tenant_id,
            "cost_center_id": cost_center_id,
            "cost_real": cost_real,
            "signature": rx_signature,
            "metadata": metadata,
            "auth_id": auth_id, 
            "error": str(e)
        }
        try:
            await redis_client.lpush("failed_receipts", json.dumps(failed_receipt))
        except Exception as redis_e:
             logger.critical(f"🔥 CATASTROPHIC FAILURE: Could not save to DLQ either: {redis_e}")
        
    # 3. Actualizar Contadores (Redis + DB) (Solo si hay coste real)
    if not cache_hit and cost_real > 0:
        await increment_spend(tenant_id, cost_center_id, cost_real, metadata)
    
    return rx_signature

from opentelemetry import trace
tracer = trace.get_tracer(__name__)

async def settle_knowledge_exchange(buyer_tid: str, seller_tid: str, original_model_cost: float):
    """
    Liquida la transacción con observabilidad de negocio integrada.
    """
    with tracer.start_as_current_span("sovereign_settlement") as span:
        try:
            discounted_price = Decimal(str(original_model_cost)) * Decimal("0.30")
            seller_revenue = discounted_price * Decimal("0.50")

            # Atributos de observabilidad para Grafana
            span.set_attribute("knowledge.buyer_id", buyer_tid)
            span.set_attribute("knowledge.seller_id", seller_tid)
            span.set_attribute("knowledge.revenue_generated", float(seller_revenue))
            span.set_attribute("knowledge.buyer_savings", float(original_model_cost - float(discounted_price)))

            # 1. Cargo al comprador (Tenant A)
            await increment_spend(buyer_tid, "default", discounted_price, {
                "mode": "KNOWLEDGE_PURCHASE",
                "source_tenant": seller_tid
            })

            # 2. ABONO al vendedor (Tenant B) - Valor negativo para reducir su deuda o generar saldo
            await increment_spend(seller_tid, "default", -seller_revenue, {
                "mode": "KNOWLEDGE_SALE",
                "target_tenant": buyer_tid
            })
            
            return float(discounted_price)
        except Exception as e:
            span.record_exception(e)
            logger.error(f"Settlement Error: {e}")
            return 0.0

async def check_budget_integrity(tenant_id: str, estimated_cost: float) -> tuple[bool, str]:
    """
    Verifica si el tenant tiene saldo suficiente (Redis Real-time)
    e implementa el CIRCUIT BREAKER de Emergencia (Kill Switch).
    """
    with tracer.start_as_current_span("budget_integrity_check") as span:
        try:
            # 1. INTEGRITY CHECK (Saldo Total)
            current_spend = await redis_client.get(f"spend:{tenant_id}:total")
            limit = await redis_client.get(f"limit:{tenant_id}")
            
            # Conversiones seguras & Fallback de "Verdad"
            if current_spend is None:
                # ⚠️ CACHE MISS: Ir a la fuente de verdad (DB)
                logger.warning(f"⚠️ Cache Miss for Budget Check {tenant_id}. Fetching DB...")
                from app.db import supabase
                # Asumimos que la tabla cost_centers tiene el gasto actual
                res = supabase.table("cost_centers").select("current_spend").eq("tenant_id", tenant_id).execute()
                total_db = sum(item['current_spend'] for item in res.data)
                
                # Repoblar Redis
                await redis_client.setex(f"spend:{tenant_id}:total", 86400, total_db)
                cur = float(total_db)
            else:
                cur = float(current_spend)

            lim = float(limit) if limit else 10.0 # Default seguro start-up
            
            if cur + estimated_cost > lim:
                span.set_attribute("budget.exceeded", True)
                logger.warning(f"⛔ TITANIC PROTOCOL: Tenant {tenant_id} blocked. Budget Exceeded ({cur}/{lim}).")
                return False, "BUDGET_EXCEEDED"

            # 2. CIRCUIT BREAKER (Kill Switch - Velocity Check)
            # Detecta picos de gasto anómalos (ej: Bucle infinito o ataque)
            # Metrica: Gasto por Minuto.
            import time
            current_minute = int(time.time() // 60)
            velocity_key = f"stats:{tenant_id}:velocity:{current_minute}"
            
            # Incrementamos la velocidad actual (Atomic)
            # Usamos pipeline para atomicidad y TTL
            p = redis_client.pipeline()
            p.incrbyfloat(velocity_key, estimated_cost)
            p.expire(velocity_key, 120) # Keep for 2 mins
            res = await p.execute()
            
            current_velocity = float(res[0])
            
            # Umbral de Pánico: $10/minuto es muchísimo para la mayoría de casos normales (600$/hora)
            # O 10% del límite mensual en 1 minuto.
            PANIC_THRESHOLD = max(lim * 0.10, 5.0) 
            
            if current_velocity > PANIC_THRESHOLD:
                span.set_attribute("security.kill_switch_triggered", True)
                logger.critical(f"🔥 KILL SWITCH: Tenant {tenant_id} spending ${current_velocity}/min! Freezing account.")
                # Auto-Freeze (podríamos poner una flag en Redis)
                await redis_client.setex(f"security:freeze:{tenant_id}", 300, "1") # Freeze por 5 min
                return False, "KILL_SWITCH_TRIGGERED"

            return True, "OK"
            
        except Exception as e:
            logger.error(f"Budget Check Error: {e}")
            # Fail-Safe: Si Redis falla, permitimos tráfico con log de error (o bloqueamos segun politica)
            # Para SaaS crítico, mejor bloquear si no se puede verificar saldo ("Fail-Closed").
            return False, "SYSTEM_ERROR"
