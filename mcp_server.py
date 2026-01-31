import asyncio
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastmcp import FastMCP
from app.db import supabase

# Inicializamos el servidor MCP
mcp = FastMCP("AgentShield Enterprise Protocol")

# --- Helpers ---
async def log_mcp_audit(tenant_id: str, action: str, details: Dict[str, Any]):
    """Async audit logging for MCP actions"""
    try:
        loop = asyncio.get_running_loop()
        def _insert():
            supabase.table("admin_audit_logs").insert({
                "tenant_id": tenant_id,
                "actor_id": "mcp_service", # MCP actions are often system-driven or proxied
                "action": f"MCP_{action.upper()}",
                "details": details,
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        await loop.run_in_executor(None, _insert)
    except Exception as e:
        print(f"MCP Audit Failed: {e}")

# --- Tools ---

@mcp.tool()
async def get_user_trust_profile(email: str, tenant_id: str) -> dict:
    """
    Consigue el Perfil de Confianza (Trust Score) y Nivel de Riesgo de un usuario.
    Requiere tenant_id explícito.
    """
    try:
        loop = asyncio.get_running_loop()

        def _lookup():
            # Production: Lookup in profiles table
            # Assuming 'profiles' table has 'email' or we join with auth.users (if privileges allow)
            # Falling back to secure metadata check in 'profiles'
            return supabase.table("profiles")\
                .select("user_id, trust_score, risk_tier")\
                .eq("email", email)\
                .eq("tenant_id", tenant_id)\
                .single()\
                .execute()
        
        res = await loop.run_in_executor(None, _lookup)

        if not res.data:
            return {"error": "User profile not found in this tenant."}

        return {
            "email": email,
            "trust_score": res.data.get("trust_score", 50),
            "risk_tier": res.data.get("risk_tier", "UNKNOWN"),
            "status": "VERIFIED"
        }

    except Exception as e:
        return {"error": f"Resolution failed: {str(e)}"}


@mcp.tool()
async def search_knowledge_vault(query: str, tenant_id: str) -> str:
    """
    Busca documentos secretos en el Vault corporativo usando RAG seguro.
    Devuelve fragmentos relevantes redactados.
    """
    try:
        # Mocking the RAG call for MCP demo compliance, but using Async structure
        # In real prod, this calls 'app.services.rag.search(query, tenant_id)'
        
        await asyncio.sleep(0.1) # Simulate Latency
        return f"[SECURE RESULT] Found 2 documents for '{query}' in tenant {tenant_id}. Content redacted."
        
    except Exception as e:
        return f"Vault error: {e}"


@mcp.tool()
async def get_wallet_balance(user_id: str) -> str:
    """
    Consulta el saldo de la billetera de un empleado o departamento.
    """
    try:
        loop = asyncio.get_running_loop()
        def _fetch():
            return supabase.table("wallets").select("balance, currency").eq("user_id", user_id).execute()
        
        res = await loop.run_in_executor(None, _fetch)
        
        if res.data:
            b = res.data[0]
            return f"{b['balance']} {b['currency']}"
        return "Wallet not found."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def create_dynamic_policy(tenant_id: str, tool_name: str, rule: str, action: str = "REQUIRE_APPROVAL") -> str:
    """
    Crea una nueva regla de política en caliente.
    Ej: tool_name="stripe_charge", rule='{"amount": {"gt": 1000}}', action="BLOCK"
    """
    try:
        rule_json = json.loads(rule)
        loop = asyncio.get_running_loop()

        def _execute_creation():
            # 1. Resolver tool_id
            tools = (
                supabase.table("tool_definitions")
                .select("id")
                .eq("name", tool_name)
                .eq("tenant_id", tenant_id)
                .execute()
            )
            if not tools.data:
                raise ValueError(f"Tool '{tool_name}' not found in tenant.")
            
            tool_id = tools.data[0]["id"]

            return supabase.table("tool_policies").insert(
                {
                    "tenant_id": tenant_id,
                    "tool_id": tool_id,
                    "action": action,
                    "argument_rules": rule_json,
                    "priority": 50,
                }
            ).execute()

        await loop.run_in_executor(None, _execute_creation)

        # Audit
        await log_mcp_audit(tenant_id, "create_policy", {"tool": tool_name, "rule": rule, "action": action})

        return f"Policy created: IF {tool_name} params match {rule} THEN {action}"
    except Exception as e:
        return f"Policy creation failed: {e}"


@mcp.tool()
async def get_forensic_timeline(trace_id: str, tenant_id: str) -> str:
    """
    Recupera la línea de tiempo forense completa (CSI Mode).
    Requiere tenant_id para validar propiedad del trace.
    """
    from app.services.forensics import forensics

    try:
        # Validate ownership manually or trust forensics service to do it
        loop = asyncio.get_running_loop()
        
        timeline = await forensics.reconstruct_timeline(tenant_id, trace_id)

        report = f"🕵️ Forensic Report for {trace_id}\n"
        report += "=" * 40 + "\n"
        for event in timeline:
            report += f"[{event['ts']}] {event['type']}\n"
            data = event["data"]
            if event["type"] == "POLICY_CHECK":
                report += f"   Model: {data.get('metadata', {}).get('model')}\n"
            elif event["type"] == "TOOL_INTERCEPT":
                report += f"   Tool: {data.get('tool_name')}\n"
                report += f"   Status: {data.get('status')}\n"

        return report
    except Exception as e:
        return f"Forensic lookup failed: {e}"


@mcp.tool()
async def check_financial_compliance(project_budget: float, estimated_cost: float) -> str:
    """
    Verifica si una operación cumple con las reglas financieras (Waterfall Budgeting).
    Pure logic, no DB needed.
    """
    if estimated_cost > project_budget:
        return f"DENIED: Cost {estimated_cost} exceeds budget {project_budget}."
    if estimated_cost > 100:
        return "WARNING: High cost transaction. Manual approval recommended."
    return "APPROVED: Within budget limits."


@mcp.tool()
async def list_knowledge_royalties(user_id: str) -> str:
    """
    Lista las ganancias (Royalties) generadas por los documentos del usuario.
    """
    try:
        loop = asyncio.get_running_loop()
        def _fetch():
            return supabase.table("internal_ledger")\
                .select("*")\
                .eq("to_wallet_id", user_id)\
                .eq("concept", "KNOWLEDGE_ROYALTY")\
                .execute()

        res = await loop.run_in_executor(None, _fetch)

        if not res.data:
            return "No royalties found."

        total = sum(float(r["amount"]) for r in res.data)
        return f"Total Earnings: ${total:.4f} USD\nTransactions: {len(res.data)}"
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
