# app/services/tool_governor.py
import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.db import supabase
from app.services.identity import VerifiedIdentity

logger = logging.getLogger("agentshield.tools")


class ToolDecision(BaseModel):
    action: str  # ALLOW, BLOCK, REQUIRE_APPROVAL
    reason: str
    approval_id: str | None = None
    cost: float = 0.0


class ToolGovernor:
    async def inspect_tool_calls(
        self, identity: VerifiedIdentity, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Analiza las herramientas solicitadas por el LLM.
        Si alguna viola la política, la bloquea o la sustituye por una solicitud de aprobación.
        """
        sanitized_calls = []

        for call in tool_calls:
            # Handle potential missing keys safely
            function_data = call.get("function", {})
            function_name = function_data.get("name", "unknown_tool")
            arguments_str = function_data.get("arguments", "{}")
            try:
                args = json.loads(arguments_str)
            except:
                args = {}

            # 1. EVALUAR POLÍTICA
            decision = await self._evaluate_policy(identity, function_name, args)

            if decision.action == "ALLOW":
                # Pasa limpio. Añadimos el coste al recibo (lógica externa)
                sanitized_calls.append(call)
                logger.info(f"✅ Tool Allowed: {function_name} for {identity.email}")

            elif decision.action == "BLOCK":
                # Hack: Reemplazamos la llamada real por una función falsa que devuelve el error al LLM
                sanitized_calls.append(
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": "system_notification",  # Función interna
                            "arguments": json.dumps(
                                {"type": "error", "message": f"🚫 Tool Blocked: {decision.reason}"}
                            ),
                        },
                    }
                )
                logger.warning(f"🚫 Tool Blocked: {function_name} ({decision.reason})")

            elif decision.action == "REQUIRE_APPROVAL":
                # CREAR SOLICITUD DE APROBACIÓN (2-Man Rule)
                try:
                    approval = (
                        supabase.table("tool_approvals")
                        .insert(
                            {
                                "tenant_id": identity.tenant_id,
                                "user_id": identity.user_id,
                                "tool_name": function_name,
                                "tool_arguments": args,
                                "status": "PENDING",
                            }
                        )
                        .execute()
                    )

                    approval_id = "UNKNOWN"
                    if approval.data:
                        approval_id = approval.data[0]["id"]

                    # Le decimos al LLM que notifique al usuario
                    sanitized_calls.append(
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": "system_notification",
                                "arguments": json.dumps(
                                    {
                                        "type": "approval_required",
                                        "message": f"⚠️ High-Risk Action Paused. Supervisor approval required. ID: {approval_id}",
                                        "approval_link": f"https://dashboard.agentshield.com/approvals/{approval_id}",
                                    }
                                ),
                            },
                        }
                    )
                    logger.warning(
                        f"⚠️ Tool Approval Required: {function_name} -> ID: {approval_id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to create approval: {e}")
                    # En caso de error de DB, bloqueamos por seguridad
                    sanitized_calls.append(
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": "system_notification",
                                "arguments": json.dumps(
                                    {
                                        "type": "error",
                                        "message": "🚫 System Error during approval creation.",
                                    }
                                ),
                            },
                        }
                    )

        return sanitized_calls

    async def _evaluate_policy(
        self, identity: VerifiedIdentity, tool_name: str, args: dict
    ) -> ToolDecision:
        """
        Busca reglas dinámicas en la base de datos. Cero hardcoding.
        """
        try:
            # 1. Buscar políticas activas para esta herramienta
            # Query optimizada: Trae políticas para el Tenant + Tool name
            # Nota: Esto asume una relación o que tool_policies tiene un campo 'tool_name' o hacemos join.
            # Para eficiencia, asumamos que 'tool_name' está desnormalizado o hacemos join con definitions.
            # Usamos una vista o query directa.

            # 1. Buscar políticas activas para esta herramienta
            # FIX: Usamos "Embedding Resource" para filtrar por nombre de herramienta en la tabla relacionada
            # tool_policies -> tool_definitions (filtrar por name)

            policies_res = (
                supabase.table("tool_policies")
                .select("*, tool_definitions!inner(name)")
                .eq("tool_definitions.name", tool_name)
                .eq("tenant_id", identity.tenant_id)
                .eq("is_active", True)
                .order("priority", desc=True)
                .execute()
            )

            policies = policies_res.data or []

            # 2. Iterar políticas
            for p in policies:
                # A. Filtro de Rol
                if p.get("target_role") and p["target_role"] != identity.role:
                    continue

                # B. Filtro de Departamento
                if p.get("target_dept_id") and str(p["target_dept_id"]) != str(
                    identity.dept_id or ""
                ):
                    continue

                # C. Evaluar Argumentos (Logic Engine Simple)
                # Regla en DB: {"amount": {"gt": 500}}
                rule_logic = p.get("argument_rules", {})
                violation_found = False

                if not rule_logic:
                    # Si no hay reglas de argumentos, la política aplica siempre (ej: Bloquear herramienta para Becarios)
                    violation_found = True
                else:
                    # Verificar condiciones
                    for arg_key, conditions in rule_logic.items():
                        arg_val = args.get(arg_key)
                        if arg_val is None:
                            continue  # Argumento no presente, skip check? O fail? (Default permissive here)

                        # Soporte básico: gt (greater than), lt (less than), eq (equal)
                        if isinstance(conditions, dict):
                            if "gt" in conditions and isinstance(arg_val, (int, float)):
                                if arg_val > conditions["gt"]:
                                    violation_found = True
                            if "lt" in conditions and isinstance(arg_val, (int, float)):
                                if arg_val < conditions["lt"]:
                                    violation_found = True
                        elif conditions == arg_val:
                            # Igualdad directa
                            violation_found = True

                if violation_found:
                    return ToolDecision(
                        action=p["action"],
                        reason=f"Policy triggered: {p.get('name', 'Rule Violation')}",
                        approval_id=p.get(
                            "approval_group"
                        ),  # Grupo que debe aprobar si es REQUIRE_APPROVAL
                    )

            # 4. Default Allow
            return ToolDecision(action="ALLOW", reason="No restrictions found")

        except Exception as e:
            logger.error(f"Policy DB Error: {e}")
            # Fail Safe: Block on DB error? Or Allow?
            # Security First -> Block if we can't verify policies.
            return ToolDecision(action="BLOCK", reason="Policy Verification System Unavailable")


governor = ToolGovernor()
