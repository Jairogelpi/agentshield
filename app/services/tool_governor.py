# app/services/tool_governor.py
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.db import supabase
from app.services.identity import VerifiedIdentity
import logging

logger = logging.getLogger("agentshield.tools")

class ToolDecision(BaseModel):
    action: str              # ALLOW, BLOCK, REQUIRE_APPROVAL
    reason: str
    approval_id: Optional[str] = None
    cost: float = 0.0

class ToolGovernor:
    async def inspect_tool_calls(
        self, 
        identity: VerifiedIdentity, 
        tool_calls: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analiza las herramientas solicitadas por el LLM.
        Si alguna viola la política, la bloquea o la sustituye por una solicitud de aprobación.
        """
        sanitized_calls = []
        
        for call in tool_calls:
            # Handle potential missing keys safely
            function_data = call.get('function', {})
            function_name = function_data.get('name', 'unknown_tool')
            arguments_str = function_data.get('arguments', '{}')
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
                sanitized_calls.append({
                    "id": call['id'],
                    "type": "function",
                    "function": {
                        "name": "system_notification", # Función interna
                        "arguments": json.dumps({
                            "type": "error", 
                            "message": f"🚫 Tool Blocked: {decision.reason}"
                        })
                    }
                })
                logger.warning(f"🚫 Tool Blocked: {function_name} ({decision.reason})")

            elif decision.action == "REQUIRE_APPROVAL":
                # CREAR SOLICITUD DE APROBACIÓN (2-Man Rule)
                try:
                    approval = supabase.table("tool_approvals").insert({
                        "tenant_id": identity.tenant_id,
                        "user_id": identity.user_id,
                        "tool_name": function_name,
                        "tool_arguments": args,
                        "status": "PENDING"
                    }).execute()
                    
                    approval_id = "UNKNOWN"
                    if approval.data:
                        approval_id = approval.data[0]['id']
                    
                    # Le decimos al LLM que notifique al usuario
                    sanitized_calls.append({
                        "id": call['id'],
                        "type": "function",
                        "function": {
                            "name": "system_notification",
                            "arguments": json.dumps({
                                "type": "approval_required",
                                "message": f"⚠️ High-Risk Action Paused. Supervisor approval required. ID: {approval_id}",
                                "approval_link": f"https://dashboard.agentshield.com/approvals/{approval_id}"
                            })
                        }
                    })
                    logger.warning(f"⚠️ Tool Approval Required: {function_name} -> ID: {approval_id}")
                except Exception as e:
                    logger.error(f"Failed to create approval: {e}")
                    # En caso de error de DB, bloqueamos por seguridad
                    sanitized_calls.append({
                        "id": call['id'],
                        "type": "function",
                        "function": {
                            "name": "system_notification",
                            "arguments": json.dumps({
                                "type": "error", 
                                "message": f"🚫 System Error during approval creation."
                            })
                        }
                    })

        return sanitized_calls

    async def _evaluate_policy(self, identity: VerifiedIdentity, tool_name: str, args: Dict) -> ToolDecision:
        # Lógica para buscar en 'tool_definitions' y 'tool_policies'
        # En una impl real:
        # tool_def = supabase.table("tool_definitions").select("*").eq("name", tool_name).execute()
        # policies = supabase.table("tool_policies").select("*").eq("tool_id", tool_def.id).execute()
        
        # Para DEMO rápida y robustez sin DB poblada:
        
        # Ejemplo Hardcodeado para demostración solicitada:
        if tool_name == "transfer_funds" or tool_name == "stripe_charge":
            amount = args.get("amount", 0)
            # Regla de prueba: > 1000 requiere aprobación
            if isinstance(amount, (int, float)) and amount > 500:
                return ToolDecision(action="REQUIRE_APPROVAL", reason="Amount > $500 exceeds auto-approval limit")
            
        if tool_name == "database_delete":
             return ToolDecision(action="BLOCK", reason="Destructive action strictly prohibited")
            
        # Role check mock
        if identity.role and "intern" in identity.role.lower():
            if tool_name in ["deploy_prod", "access_prod_db"]:
                return ToolDecision(action="BLOCK", reason="Interns cannot modify Production")
                
        return ToolDecision(action="ALLOW", reason="Policy Check OK")

governor = ToolGovernor()
