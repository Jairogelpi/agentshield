from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from app.services.identity import verify_identity_envelope, VerifiedIdentity
from app.services.trust_system import trust_system
from app.services.pii_guard import pii_guard
from app.services.llm_gateway import execute_with_resilience
from app.services.limiter import limiter 
from app.services.receipt_manager import receipt_manager
from app.services.semantic_router import semantic_router
import logging
import json
import uuid

router = APIRouter()
logger = logging.getLogger("agentshield.proxy")

@router.post("/v1/chat/completions")
async def universal_proxy(
    request: Request,
    background_tasks: BackgroundTasks,
    identity: VerifiedIdentity = Depends(verify_identity_envelope)
):
    """
    El Corazón del AgentShield OS.
    Flujo: Identity -> Trust -> Semantic -> PII -> Budget -> Execution -> Audit
    """
    trace_id = f"tr_{uuid.uuid4().hex[:8]}"
    
    # 1. PARSE REQUEST & CONTEXT
    # ---------------------------------------------------------
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    requested_model = body.get("model", "agentshield-fast")
    messages = body.get("messages", [])
    
    # 2. TRUST ENGINE ENFORCEMENT (Decision Graph Node 1)
    # ---------------------------------------------------------
    trust_policy = await trust_system.enforce_policy(
        str(identity.tenant_id), 
        identity.user_id, 
        requested_model
    )
    
    if trust_policy["requires_approval"]:
        logger.warning(f"🛡️ TRUST LOCK: User {identity.email} score {trust_policy['trust_score']}")
        raise HTTPException(403, detail=f"⛔ Trust Lock: {trust_policy['blocking_reason']}")

    effective_model = trust_policy["effective_model"]
    body["model"] = effective_model 
    
    # 3. PII & DLP GUARD (Decision Graph Node 2)
    # ---------------------------------------------------------
    pii_result = await pii_guard.scan(messages)
    
    if pii_result.get("blocked"):
        background_tasks.add_task(
            trust_system.adjust_score,
            tenant_id=str(identity.tenant_id),
            user_id=identity.user_id,
            delta=-20,
            reason="Security Block: High Sensitivity PII detected",
            event_type="PII_BLOCK",
            metadata={"severity": "HIGH", "findings": pii_result.get("findings_count")}
        )
        raise HTTPException(400, "🛡️ AgentShield Security: Envío bloqueado por datos altamente sensibles.")

    elif pii_result.get("changed"):
        background_tasks.add_task(
            trust_system.adjust_score,
            tenant_id=str(identity.tenant_id),
            user_id=identity.user_id,
            delta=-5,
            reason="Security Warning: PII redacted automatically",
            event_type="PII_REDACT",
            metadata={"severity": "MEDIUM", "findings": pii_result.get("findings_count")}
        )
        messages = pii_result.get("cleaned_messages")

    # 4. BUDGET LIMITER (Decision Graph Node 3)
    # ---------------------------------------------------------
    can_spend, limit_msg = await limiter.check_velocity_and_budget(identity)
    
    if not can_spend:
        background_tasks.add_task(
            trust_system.adjust_score,
            tenant_id=str(identity.tenant_id),
            user_id=identity.user_id,
            delta=-2,
            reason="Rate Limit Exceeded",
            event_type="VELOCITY_VIOLATION"
        )
        raise HTTPException(429, f"📉 Budget/Rate Limit: {limit_msg}")

    # 5. EXECUTION ROUTER
    # ---------------------------------------------------------
    try:
        response = await execute_with_resilience(
            model=effective_model,
            messages=messages,
            user_id=identity.user_id
        )
    except Exception as e:
        logger.error(f"Gateway Error: {e}")
        raise HTTPException(502, "AI Provider Gateway Error")

    # 6. RECEIPT WRITER (Forensics)
    # ---------------------------------------------------------
    decision_metadata = {
        "original_model": requested_model,
        "effective_model": effective_model,
        "trust_score_snapshot": trust_policy["trust_score"],
        "trust_mode": trust_policy["mode"],
        "pii_redacted": pii_result.get("changed", False),
        "policy_hash": "ENTERPRISE_CORE_V1"
    }

    background_tasks.add_task(
        receipt_manager.create_and_sign_receipt,
        tenant_id=str(identity.tenant_id),
        user_id=identity.user_id,
        request_data={"model": effective_model, "trace_id": trace_id},
        response_data=response,
        metadata=decision_metadata
    )

    # 7. RESPONSE WITH EDUCATIONAL LAYER
    # ---------------------------------------------------------
    content = json.loads(response.json()) if hasattr(response, "json") else response
    final_response = JSONResponse(content=content)
    
    # Header A: Estado actual
    final_response.headers["X-AgentShield-Trust-Score"] = str(trust_policy["trust_score"])
    final_response.headers["X-AgentShield-Trace-ID"] = trace_id
    
    # Header B: Explicación de Restricciones (Auto-educación)
    if trust_policy["mode"] == "restricted":
        final_response.headers["X-AgentShield-Alert"] = "warning"
        final_response.headers["X-AgentShield-Message"] = (
            "⚠️ Acceso a modelos Premium restringido temporalmente. "
            "Mantén 24h sin incidentes de seguridad para recuperar el nivel."
        )
    
    elif trust_policy["mode"] == "supervised":
        final_response.headers["X-AgentShield-Alert"] = "error"
        final_response.headers["X-AgentShield-Message"] = (
            "⛔ Nivel de confianza crítico. Todas tus acciones requieren aprobación manual. "
            "Contacta a tu responsable o completa el módulo de re-entrenamiento."
        )

    if effective_model != requested_model:
        final_response.headers["X-AgentShield-Notice"] = "Model Downgraded due to Risk Policy"
    
    if pii_result.get("changed"):
        final_response.headers["X-AgentShield-Security"] = "Content Redacted"

    return final_response
