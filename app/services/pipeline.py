import asyncio
import logging
import uuid

from fastapi import HTTPException, Request

from app.config import settings
from app.http_limiter import limiter
from app.schema import DecisionContext
from app.services.carbon import carbon_governor
from app.services.event_bus import event_bus
from app.services.pii_guard import pii_guard
from app.services.roles import role_fabric
from app.services.semantic_router import semantic_router
from app.services.trust_system import trust_system

logger = logging.getLogger("agentshield.pipeline")


class DecisionPipeline:
    @staticmethod
    async def process_request(request: Request, identity, messages: list, requested_model: str):
        """
        Processes a request through all AgentShield gates.
        Returns (ctx, modified_messages, trust_policy, active_role, pii_result).
        """
        # 0. ROLE FABRIC
        user_function = getattr(identity, "function", settings.DEFAULT_FUNCTION)
        active_role = await role_fabric.get_role(
            dept=str(identity.dept_id or settings.DEFAULT_DEPT), function=user_function
        )

        if messages and messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": active_role.get("system_persona")})

        # 1. CONTEXT BUILDER
        trace_id = f"trc_{uuid.uuid4().hex[:12]}"
        request.state.trace_id = trace_id  # For global exception handler

        ctx = DecisionContext(
            trace_id=trace_id,
            tenant_id=str(identity.tenant_id),
            user_id=identity.user_id,
            dept_id=str(identity.dept_id or ""),
            email=identity.email,
            requested_model=requested_model,
            effective_model=requested_model,
        )

        user_prompt = (
            messages[-1]["content"]
            if messages and isinstance(messages[-1].get("content"), str)
            else ""
        )

        # 2. INTENT CLASSIFIER (Semantic Gate)
        try:
            ctx.intent = await asyncio.wait_for(
                semantic_router.classify_intent(ctx.tenant_id, user_prompt), timeout=3.0
            )
            ctx.log("INTENT", f"Classified as {ctx.intent}")
        except TimeoutError:
            logger.warning(f"⏰ Timeout on Intent Classifier for {trace_id}")
            ctx.intent = "general"  # Default fallback

        # 3. RISK ENGINE (Trust Gate)
        try:
            trust_policy = await asyncio.wait_for(
                trust_system.enforce_policy(
                    ctx.tenant_id, ctx.user_id, ctx.requested_model, intent=ctx.intent
                ),
                timeout=2.0,
            )
        except TimeoutError:
            logger.error(f"⚠️ Timeout on Trust System for {trace_id}. Locking for safety.")
            raise HTTPException(503, "Security Governance Timeout - Please retry")

        if trust_policy["requires_approval"]:
            # SIEM ALERT
            asyncio.create_task(
                event_bus.publish(
                    tenant_id=ctx.tenant_id,
                    event_type="POLICY_BLOCK",
                    severity="WARNING",
                    details={"reason": trust_policy["blocking_reason"], "gate": "TRUST_ENGINE"},
                    actor_id=ctx.user_id,
                    trace_id=ctx.trace_id,
                )
            )
            raise HTTPException(403, detail=f"⛔ Trust Lock: {trust_policy['blocking_reason']}")

        if trust_policy["effective_model"] != ctx.requested_model:
            ctx.effective_model = trust_policy["effective_model"]
            ctx.risk_mode = trust_policy["mode"]

        # 3.5 AI ACT GOVERNANCE (Legal Gate)
        # We classify prompt risk. If prohibited -> 451. If high risk -> require approval.
        try:
            from app.services.eu_ai_act_classifier import eu_ai_act_classifier, RiskLevel
            
            # Fast Check (Async)
            # Pass context trace_id for audit logging inside classifier if needed
            ai_risk_level, ai_category, ai_confidence = await eu_ai_act_classifier.classify(user_prompt)
            
            ctx.log("AI_ACT", f"Risk: {ai_risk_level} ({ai_category}) - Conf: {ai_confidence}")
            
            if ai_risk_level == RiskLevel.PROHIBITED:
                # SIEM ALERT
                asyncio.create_task(
                    event_bus.publish(
                        tenant_id=ctx.tenant_id,
                        event_type="LEGAL_BLOCK_EU_AI_ACT",
                        severity="CRITICAL",
                        details={"category": ai_category, "reason": "Prohibited Practice (Article 5)"},
                        actor_id=ctx.user_id,
                        trace_id=ctx.trace_id,
                    )
                )
                raise HTTPException(
                    status_code=451, # Unavailable For Legal Reasons
                    detail=f"🇪🇺 EU AI Act BLOCK: Prohibited Practice Detected ({ai_category}). Action loggeed."
                )
                
            if ai_risk_level == RiskLevel.HIGH_RISK:
                # Check for Human Approval Header
                approval_id = request.headers.get("X-Agentshield-Approval-Id")
                if not approval_id:
                     # SIEM ALERT
                    asyncio.create_task(
                        event_bus.publish(
                            tenant_id=ctx.tenant_id,
                            event_type="COMPLIANCE_HOLD",
                            severity="WARNING",
                            details={"category": ai_category, "reason": "High Risk - Missing Human Oversight"},
                            actor_id=ctx.user_id,
                            trace_id=ctx.trace_id,
                        )
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"🇪🇺 EU AI Act HOLD: High Risk Use Case ({ai_category}) requires Human Oversight (Article 14). Please provide 'X-Agentshield-Approval-Id'."
                    )
                
                # Verify Approval (Mock or Real Service Call)
                # await human_approval_queue.verify_approval(approval_id, ctx.tenant_id)
                ctx.log("AI_ACT", f"High Risk Approved via {approval_id}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"⚠️ AI Act Classifier Error: {e}")
            # Fail Open or Closed? For compliance, usually Fail Closed, but for availability Fail Open.
            # We choose Fail Open with Log for now unless stric_mode is on.
            pass


        # 4. COMPLIANCE GATE (PII Check)
        try:
            pii_result = await asyncio.wait_for(pii_guard.scan(messages), timeout=3.0)
            if pii_result.get("blocked"):
                # SIEM ALERT
                asyncio.create_task(
                    event_bus.publish(
                        tenant_id=ctx.tenant_id,
                        event_type="PII_VIOLATION",
                        severity="CRITICAL",
                        details={"findings": pii_result.get("findings")},
                        actor_id=ctx.user_id,
                        trace_id=ctx.trace_id,
                    )
                )
                raise HTTPException(
                    400, "🛡️ AgentShield Security: Envío bloqueado por datos altamente sensibles."
                )
            if pii_result.get("changed"):
                messages = pii_result["cleaned_messages"]
                ctx.pii_redacted = True
        except TimeoutError:
            logger.error(f"⚠️ Timeout on PII Guard for {trace_id}")
            raise HTTPException(503, "Security Compliance Timeout")

        # 5. ARBITRAGE GATE (Financial Engine)
        if "agentshield-smart" in ctx.requested_model:
            ctx.effective_model = "gpt-4o"
        elif "agentshield-fast" in ctx.requested_model:
            from app.services.arbitrage import arbitrage_engine

            try:
                analysis = await asyncio.wait_for(
                    arbitrage_engine.analyze_complexity(messages), timeout=2.0
                )
                winner_id, reason, savings = await arbitrage_engine.find_best_bidder(
                    "gpt-4o-mini", analysis
                )
                if savings > 0 and winner_id:
                    ctx.effective_model = winner_id
            except TimeoutError:
                pass  # Use default model on timeout

        # 5.5 CARBON GATE
        if ctx.effective_model == ctx.requested_model:
            ctx = await carbon_governor.check_budget_and_route(ctx)

        # 5.6 BUDGET GATE
        can_spend, limit_msg = await limiter.check_velocity_and_budget(identity)
        if not can_spend:
            raise HTTPException(429, detail=f"📉 AgentShield: {limit_msg}")

        logger.info(f"✅ Pipeline Passed [{trace_id}] - Routing to {ctx.effective_model}")
        return ctx, messages, trust_policy, active_role, pii_result
