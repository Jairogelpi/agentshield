import hashlib
import json
import logging

from app.db import redis_client, supabase
from app.services.llm_gateway import execute_with_resilience

logger = logging.getLogger("agentshield.semantic")


class SemanticRouter:
    async def classify_intent(self, tenant_id: str, prompt: str) -> str:
        """
        Determina la intención del usuario basándose en las definiciones activas en DB.
        Usa caché semántico para no gastar dinero clasificando lo mismo 2 veces.
        """
        # 1. Check Cache Rápido
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_key = f"intent:{tenant_id}:{prompt_hash}"
        cached = await redis_client.get(cache_key)
        if cached:
            return cached.decode()

        # 2. Cargar Definiciones Vivas (Sin Hardcoding)
        try:
            res = (
                supabase.table("intent_definitions")
                .select("name, description")
                .eq("tenant_id", tenant_id)
                .execute()
            )
            intents = res.data or []
        except Exception as e:
            logger.error(f"Failed to fetch intents: {e}")
            intents = []

        if not intents:
            return "GENERAL"  # Fallback si no hay configuración

        # 3. Construir Prompt del Clasificador
        # Le damos a la IA la lista dinámica de categorías
        categories_str = "\n".join([f"- {i['name']}: {i['description']}" for i in intents])

        system_prompt = f"""
        You are a Semantic Router for a Corporate AI System.
        Classify the user prompt into exactly ONE of these categories:
        {categories_str}
        - GENERAL: If it doesn't fit clearly.
        
        Return ONLY the category name. No markdown.
        """

        # 4. Ejecutar Clasificación (Usamos modelo barato/rápido)
        try:
            # Necesitamos un user_id fake para el gateway system call
            response = await execute_with_resilience(
                tier="agentshield-fast",  # Importante: usar tier rápido
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt[:1000]},  # Truncar para velocidad
                ],
                user_id="system_classifier",
            )

            # Adaptamos según si retorna dict o objeto
            if isinstance(response, dict):
                intent = response["choices"][0]["message"]["content"].strip().upper()
            else:
                intent = response.choices[0].message.content.strip().upper()

        except Exception as e:
            logger.warning(f"Classification failed: {e}. Defaulting to GENERAL.")
            intent = "GENERAL"

        # 5. Guardar en Caché (TTL 24h)
        await redis_client.setex(cache_key, 86400, intent)

        return intent

    async def check_semantic_budget(self, identity, intent: str):
        """
        Verifica las reglas del CFO para este Depto + Intención.
        Retorna: (is_allowed, penalty_multiplier, reason)
        """
        if not identity.dept_id:
            return True, 1.0, "No department context"

        try:
            # Buscar regla específica para el departamento
            # Necesitamos join con intent_definitions para filtrar por nombre
            # Supabase-py join syntax is tricky, doing two-step lookup for safety or use RPC if available.

            # Step 1: Resolve Intent ID
            res_intent = (
                supabase.table("intent_definitions")
                .select("id")
                .eq("name", intent)
                .eq("tenant_id", identity.tenant_id)
                .execute()
            )

            if not res_intent.data:
                return True, 1.0, "Unknown intent (Allowed)"

            intent_id = res_intent.data[0]["id"]

            # Step 2: Resolve Budget Rule
            res_budget = (
                supabase.table("semantic_budgets")
                .select("*")
                .eq("intent_id", intent_id)
                .eq("department_id", identity.dept_id)
                .execute()
            )

            budget_rule = res_budget.data[0] if res_budget.data else None

            if not budget_rule:
                # Ver si hay regla global (dept_id is null)
                res_global = (
                    supabase.table("semantic_budgets")
                    .select("*")
                    .eq("intent_id", intent_id)
                    .is_("department_id", "null")
                    .execute()
                )
                budget_rule = res_global.data[0] if res_global.data else None

            if not budget_rule:
                return True, 1.0, "No semantic restrictions checked"

            # Lógica de CFO
            action = budget_rule.get("out_of_scope_action", "ALLOW")

            if action == "BLOCK":
                return (
                    False,
                    0.0,
                    f"Department '{identity.dept_id}' is BLOCKED from '{intent}' tasks.",
                )

            if action == "PENALTY":
                markup = float(budget_rule.get("penalty_multiplier", 1.0))
                return True, markup, f"Allowed with {markup}x surcharge penalty."

            if action == "APPROVAL":
                # Todavía no implementado workflow de aprobación
                return False, 0.0, "Requires Management Approval (Not Implemented)"

            return True, 1.0, "Allowed"

        except Exception as e:
            logger.error(f"Semantic budget check error: {e}")
            return True, 1.0, "Fail Open (Error)"


semantic_router = SemanticRouter()
