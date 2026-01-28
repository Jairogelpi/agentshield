import asyncio
from fastapi import HTTPException, Request
from app.schema import DecisionContext
from app.services.roles import role_fabric
from app.services.semantic_router import semantic_router
from app.services.trust_system import trust_system
from app.services.pii_guard import pii_guard
from app.services.carbon import carbon_governor
from app.limiter import limiter

logger = logging.getLogger("agentshield.pipeline")

class DecisionPipeline:
    @staticmethod
    async def process_request(request: Request, identity, messages: list, requested_model: str):
        """
        Processes a request through all AgentShield gates.
        Returns (ctx, modified_messages, trust_policy, active_role, pii_result).
        """
        # 0. ROLE FABRIC
        user_function = getattr(identity, "function", "Employee")
        active_role = await role_fabric.get_role(
            dept=str(identity.dept_id or "General"), function=user_function
        )

        if messages and messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": active_role.get("system_persona")})

        # 1. CONTEXT BUILDER
        trace_id = f"trc_{uuid.uuid4().hex[:12]}"
        request.state.trace_id = trace_id # For global exception handler
        
        ctx = DecisionContext(
            trace_id=trace_id,
            tenant_id=str(identity.tenant_id),
            user_id=identity.user_id,
            dept_id=str(identity.dept_id or ""),
            email=identity.email,
            requested_model=requested_model,
            effective_model=requested_model,
        )

        user_prompt = messages[-1]["content"] if messages and isinstance(messages[-1].get("content"), str) else ""

        # 2. INTENT CLASSIFIER (Semantic Gate)
        try:
            ctx.intent = await asyncio.wait_for(
                semantic_router.classify_intent(ctx.tenant_id, user_prompt),
                timeout=3.0
            )
            ctx.log("INTENT", f"Classified as {ctx.intent}")
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Timeout on Intent Classifier for {trace_id}")
            ctx.intent = "general" # Default fallback

        # 3. RISK ENGINE (Trust Gate)
        try:
            trust_policy = await asyncio.wait_for(
                trust_system.enforce_policy(ctx.tenant_id, ctx.user_id, ctx.requested_model),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            logger.error(f"⚠️ Timeout on Trust System for {trace_id}. Locking for safety.")
            raise HTTPException(503, "Security Governance Timeout - Please retry")

        if trust_policy["requires_approval"]:
            raise HTTPException(403, detail=f"⛔ Trust Lock: {trust_policy['blocking_reason']}")
        
        if trust_policy["effective_model"] != ctx.requested_model:
            ctx.effective_model = trust_policy["effective_model"]
            ctx.risk_mode = trust_policy["mode"]

        # 4. COMPLIANCE GATE (PII Check)
        try:
            pii_result = await asyncio.wait_for(pii_guard.scan(messages), timeout=3.0)
            if pii_result.get("blocked"):
                raise HTTPException(
                    400, "🛡️ AgentShield Security: Envío bloqueado por datos altamente sensibles."
                )
            if pii_result.get("changed"):
                messages = pii_result["cleaned_messages"]
                ctx.pii_redacted = True
        except asyncio.TimeoutError:
            logger.error(f"⚠️ Timeout on PII Guard for {trace_id}")
            raise HTTPException(503, "Security Compliance Timeout")

        # 5. ARBITRAGE GATE (Financial Engine)
        if "agentshield-smart" in ctx.requested_model:
            ctx.effective_model = "gpt-4o"
        elif "agentshield-fast" in ctx.requested_model:
            from app.services.arbitrage import arbitrage_engine
            try:
                analysis = await asyncio.wait_for(arbitrage_engine.analyze_complexity(messages), timeout=2.0)
                winner_id, reason, savings = await arbitrage_engine.find_best_bidder("gpt-4o-mini", analysis)
                if savings > 0 and winner_id:
                    ctx.effective_model = winner_id
            except asyncio.TimeoutError:
                pass # Use default model on timeout

        # 5.5 CARBON GATE
        if ctx.effective_model == ctx.requested_model:
            ctx = await carbon_governor.check_budget_and_route(ctx)

        # 5.6 BUDGET GATE
        can_spend, limit_msg = await limiter.check_velocity_and_budget(identity)
        if not can_spend:
            raise HTTPException(429, detail=f"📉 AgentShield: {limit_msg}")

        logger.info(f"✅ Pipeline Passed [{trace_id}] - Routing to {ctx.effective_model}")
        return ctx, messages, trust_policy, active_role, pii_result
