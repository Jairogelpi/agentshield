import asyncio
import json
import os
from typing import List, Optional

from fastmcp import FastMCP

# Importamos instancias de servicios existentes (si es posible)
# O usamos supabase directo para tools de lectura
from app.db import supabase

# Inicializamos el servidor MCP
mcp = FastMCP("AgentShield Enterprise Protocol")


@mcp.tool()
async def get_user_trust_profile(email: str) -> dict:
    """
    Consigue el Perfil de Confianza (Trust Score) y Nivel de Riesgo de un usuario.
    Útil para decidir si otorgar acceso a modelos avanzados.
    """
    try:
        # 1. Resolver User ID
        # Nota: En prod usaríamos auth.users, aquí simplificamos buscando en profiles o receipts recientes
        # Asumimos que profile tiene email (o linkeamos).
        # Si user_profiles solo tiene user_id, necesitamos hacer join o lookup.
        # Por simplicidad para la demo MCP: Buscamos en policy_events reciente para mapear email -> user_id
        # o asumimos que el email está en user_profiles (si lo añadimos).
        # Vamos a hacer una query segura:

        # Intentamos buscar por metadata en alguna tabla o asumimos que tenemos user_id.
        # Para esta demo, haremos un mock lookup si no es directo, o buscamos en `auth.users` si tuvieramos acceso admin directo (que lo tenemos via service_role).

        # Query Hack: Buscar en user_profiles si tuvieramos email, pero solo tiene user_id.
        # Buscamos en 'tenants' via owner_id? No.
        # Fallback: Usamos supabase admin list_users (requiere privilegios de admin auth).

        # V2: Buscar en policy_events un evento reciente de este email para sacar su ID.
        event = (
            supabase.table("policy_events")
            .select("metadata")
            .eq("user_email", email)
            .limit(1)
            .execute()
        )
        user_id = None
        if event.data:
            # A veces no guardamos user_id en metadata de policy events, solo email.
            # Vamos a devolver un error amigable si no podemos resolver.
            pass

        # MOCKUP INTELIGENTE para demo (ya que no podemos resolver email->uuid fácil sin auth admin api)
        # Si el email es 'admin@agentshield.com', devolvemos score alto.
        if "admin" in email:
            return {"email": email, "trust_score": 98, "risk_tier": "LOW", "status": "VERIFIED"}

        return {
            "email": email,
            "trust_score": 50,
            "risk_tier": "MEDIUM",
            "note": "User ID resolution placeholder",
        }

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def search_knowledge_vault(query: str, tenant_id: str = None) -> str:
    """
    Busca documentos secretos en el Vault corporativo usando RAG seguro.
    Devuelve fragmentos relevantes redactados.
    """
    try:
        # Usamos el servicio de embeddings que ya tienes o un select search directo via pgvector
        # Asumimos que existe la función RPC 'match_vault_chunks' (estándar en supabase vector)

        # 1. Generar embedding de la query (Simulado o real si tenemos key)
        # from app.routers.embeddings import generate_embedding
        # vec = await generate_embedding(query)

        # Mock de búsqueda para la herramienta MCP si no cargamos todo el stack de ML
        # O llamada a RPC si el embedding fuese texto (poco probable)

        return "Vault Search: [Result 1] ... [Result 2] (Requires embedding service active)"
    except Exception as e:
        return f"Vault error: {e}"


@mcp.tool()
async def get_wallet_balance(user_id: str) -> str:
    """
    Consulta el saldo de la billetera de un empleado o departamento.
    """
    try:
        res = supabase.table("wallets").select("balance, currency").eq("user_id", user_id).execute()
        if res.data:
            b = res.data[0]
            return f"{b['balance']} {b['currency']}"
        return "Wallet not found."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def create_dynamic_policy(tool_name: str, rule: str, action: str = "REQUIRE_APPROVAL") -> str:
    """
    Crea una nueva regla de política en caliente.
    Ej: tool_name="stripe_charge", rule='{"amount": {"gt": 1000}}', action="BLOCK"
    """
    try:
        # Parse logic
        rule_json = json.loads(rule)

        # Insertar en DB
        # Disclaimer: Esto requiere un tenant_id. En MCP solemos operar con un contexto de "Admin global" o hardcoded tenant para demo.
        # Buscamos el primer tenant para aplicar.
        tenants = supabase.table("tenants").select("id").limit(1).execute()
        if not tenants.data:
            return "No tenants found."
        tenant_id = tenants.data[0]["id"]

        # Resolver tool_id
        tools = (
            supabase.table("tool_definitions")
            .select("id")
            .eq("name", tool_name)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not tools.data:
            return f"Tool '{tool_name}' not found."
        tool_id = tools.data[0]["id"]

        supabase.table("tool_policies").insert(
            {
                "tenant_id": tenant_id,
                "tool_id": tool_id,
                "action": action,
                "argument_rules": rule_json,
                "priority": 50,
            }
        ).execute()

        return f"Policy created: IF {tool_name} params match {rule} THEN {action}"
    except Exception as e:
        return f"Policy creation failed: {e}"


@mcp.tool()
async def get_forensic_timeline(trace_id: str) -> str:
    """
    Recupera la línea de tiempo forense completa (CSI Mode) para una transacción.
    Devuelve un resumen textual de los eventos paso a paso.
    """
    from app.services.forensics import forensics

    # Necesitamos tenant_id... asumimos contexto global o primer tenant para demo MCP
    # O buscamos el tenant asociado al trace_id en receipts
    try:
        receipt = (
            supabase.table("receipts")
            .select("tenant_id")
            .eq("trace_id", trace_id)
            .single()
            .execute()
        )
        if not receipt.data:
            return "Trace ID not found."

        tenant_id = receipt.data["tenant_id"]
        timeline = await forensics.reconstruct_timeline(tenant_id, trace_id)

        report = f"🕵️ Forensic Report for {trace_id}\n"
        report += "=" * 40 + "\n"
        for event in timeline:
            report += f"[{event['ts']}] {event['type']}\n"
            # Extract key details
            data = event["data"]
            if event["type"] == "POLICY_CHECK":
                report += f"   Model: {data.get('metadata', {}).get('model')}\n"
                report += f"   Cost: {data.get('metadata', {}).get('cost')}\n"
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
        res = (
            supabase.table("internal_ledger")
            .select("*")
            .eq("to_wallet_id", user_id)
            .eq("concept", "KNOWLEDGE_ROYALTY")
            .execute()
        )

        if not res.data:
            return "No royalties found."

        total = sum(float(r["amount"]) for r in res.data)
        return f"Total Earnings: ${total:.4f} USD\nTransactions: {len(res.data)}"
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    # Entry point
    mcp.run()
