# app/services/policy_copilot.py
import json
import logging
from typing import Dict, List

from litellm import completion

from app.db import supabase

logger = logging.getLogger("agentshield.copilot")

# EL PROMPT MAESTRO
SYSTEM_PROMPT_TEMPLATE = """
Eres el 'Policy Compiler' de AgentShield, un sistema de gobierno de IA.
Tu única función es traducir lenguaje natural (intenciones de seguridad) a un objeto JSON de política válido.

### TU CONTEXTO (HERRAMIENTAS REALES DISPONIBLES):
{tools_catalog}

### TU CONTEXTO (DEPARTAMENTOS Y ROLES):
- Roles válidos: 'intern', 'employee', 'manager', 'admin'
- Departamentos sugeridos: 'marketing', 'it', 'finance', 'hr', 'sales' (normaliza si es parecido)

### SCHEMA DE SALIDA (JSON ESTRICTO):
Debes devolver UN SOLO objeto JSON con esta estructura (sin markdown, sin explicaciones):
{{
    "tool_name": "nombre_exacto_de_la_herramienta_arriba",
    "target_dept": "nombre_normalizado_o_null",
    "target_role": "rol_valido_o_null",
    "action": "ALLOW" | "BLOCK" | "REQUIRE_APPROVAL",
    "approval_group": "email_o_grupo_si_requiere_aprobacion",
    "argument_rules": {{ ...json_logic... }},
    "explanation": "Breve resumen de lo que hace esta regla para confirmar al usuario"
}}

### REGLAS DE TRADUCCIÓN:
1. Si el usuario dice "nadie", "bloquear todo", target_dept y target_role son null.
2. Si menciona "gastos" o "monto", asume que el argumento de la herramienta es 'amount' o 'cost'.
   - Usa sintaxis MongoDB-style para lógica: {{"amount": {{"gt": 50}}}}
3. Si la intención es ambigua, elige la opción más segura (BLOCK o REQUIRE_APPROVAL).
4. Si la herramienta mencionada no existe en el catálogo, intenta adivinar la más cercana semánticamente o usa "global" si aplica a todas.

### EJEMPLOS:
Input: "Que los becarios no usen Stripe"
Output: {{ "tool_name": "stripe_payment", "target_role": "intern", "action": "BLOCK", "argument_rules": {{}}, "explanation": "Bloquea pagos en Stripe para rol Intern." }}

Input: "Avísame si alguien de Marketing gasta más de 500 en Ads"
Output: {{ "tool_name": "google_ads", "target_dept": "marketing", "action": "REQUIRE_APPROVAL", "approval_group": "manager", "argument_rules": {{"amount": {{"gt": 500}}}}, "explanation": "Requiere aprobación para gastos > $500 en Marketing." }}
"""


async def generate_policy_json(tenant_id: str, user_prompt: str) -> dict:
    """
    Toma una orden verbal y devuelve la estructura para 'tool_policies'.
    """

    # 1. Obtener herramientas reales para dar contexto a la IA
    try:
        res = (
            supabase.table("tool_definitions")
            .select("name, description")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        tools_list = res.data or []
    except Exception as e:
        logger.warning(f"Failed to fetch tools for copilot: {e}")
        tools_list = []

    # Formatear catálogo para el prompt
    catalog_str = "\n".join([f"- {t['name']}: {t.get('description', '')}" for t in tools_list])
    if not catalog_str:
        catalog_str = "- (No hay herramientas definidas, asume nombres estándar como 'web_search', 'dall-e-3', 'stripe_charge', 'database_query')"

    # 2. Inyectar en el Prompt
    final_prompt = SYSTEM_PROMPT_TEMPLATE.format(tools_catalog=catalog_str)

    # 3. Llamada al LLM Asíncrona (Non-blocking)
    try:
        from litellm import acompletion
        
        response = await acompletion(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": final_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        return json.loads(content)

    except Exception as e:
        logger.error(f"Copilot LLM error: {e}")
        return {
            "error": "Failed to generate policy",
            "details": str(e),
            "explanation": "Lo siento, hubo un error procesando tu solicitud. Por favor intenta ser más específico.",
        }


async def generate_custom_pii_rule(user_prompt: str) -> dict:
    """
    Genera una regla Regex a partir de una descripción natural.
    """
    system_prompt = """
    You are a PII Security Expert & Regex compiler.
    Your job is to convert a user description of sensitive data into a SAFE, HIGH-PERFORMANCE Python Regex.
    
    OUTPUT JSON FORMAT:
    {
        "regex_pattern": "r'...' ",
        "risk_score": 0-100,
        "explanation": "Brief explanation of what this matches",
        "action_recommendation": "REDACT" | "BLOCK"
    }
    
    RULES:
    1. Regex must be compatible with Python 're' module.
    2. Avoid catastrophic backtracking (be specific).
    3. If user asks to block 'everything' or 'bad words', provide a generic safe list or refuse politely in explanation.
    """

    try:
        from litellm import acompletion
        response = await acompletion(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Regex Gen Failed: {e}")
        return {"error": str(e)}
