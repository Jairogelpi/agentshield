import json
import logging
from typing import Any, Dict, Optional

from app.db import supabase
from app.services.llm_gateway import execute_with_resilience

logger = logging.getLogger("agentshield.role_architect")


class RoleArchitect:
    """
    Usa OpenAI para transformar descripciones de negocio en configuraciones técnicas.
    """

    async def auto_configure_role(
        self, tenant_id: str, description: str, user_id: str = "admin"
    ) -> dict[str, Any]:
        prompt = f"""
        Actúa como un Arquitecto de Sistemas de IA y Experto en Ciberseguridad.
        El cliente quiere crear un rol operativo basado en esta descripción: "{description}"

        Tu tarea es devolver un JSON estricto para configurar AgentShield OS con:
        1. "department": Nombre del departamento sugerido (ej: "Legal", "Sales").
        2. "function": Título del puesto sugerido (ej: "Junior Analyst").
        3. "system_persona": Un System Prompt profesional y robusto que incluya:
           - Identidad clara.
           - Protocolo de respuesta.
           - Prohibición explícita de salirse del rol.
        4. "pii_policy": "BLOCK" (si es sensible como RRHH/Finanzas o se menciona bloqueo) o "REDACT" (estándar).
        5. "default_mode": "agentshield-secure" (por defecto) o "agentshield-auto".
        6. "active_rules": Lista de 3 a 5 reglas cortas de seguridad (ej: "No Financial Advice", "DLP Active", "Block Competitor Names").

        Responde ÚNICAMENTE el objeto JSON.
        """

        # Usamos GPT-4o para garantizar la calidad del System Prompt
        response = await execute_with_resilience(
            tier="agentshield-smart",  # GPT-4o typically
            messages=[{"role": "user", "content": prompt}],
            user_id=user_id,
            temperature=0.7,
        )

        try:
            content = ""
            if hasattr(response, "choices"):
                content = response.choices[0].message.content
            elif isinstance(response, dict):
                content = response["choices"][0]["message"]["content"]

            clean_json = content.strip().replace("```json", "").replace("```", "")
            config = json.loads(clean_json)

            # Persistimos en la tabla de definiciones
            # Upsert logic: if exists based on unique constraint (tenant, dept, function)
            res = (
                supabase.table("role_definitions")
                .upsert(
                    {
                        "tenant_id": tenant_id,
                        "department": config.get("department", "General"),
                        "function": config.get("function", "Staff"),
                        "system_persona": config.get("system_persona"),
                        "pii_policy": config.get("pii_policy", "REDACT"),
                        "allowed_modes": [config.get("default_mode", "agentshield-secure")],
                        "ai_generated": True,
                        "source_description": description,
                        "metadata": {
                            "active_rules": config.get("active_rules", []),
                            "source": description,
                        },
                    },
                    on_conflict="tenant_id, department, function",
                )
                .execute()
            )

            return res.data[0] if res.data else config

        except Exception as e:
            logger.error(f"Role Architect Failed: {e}")
            # Fallback safe config
            return {
                "department": "IT",
                "function": "Fallback Agent",
                "system_persona": "You are a helpful assistant.",
                "pii_policy": "REDACT",
                "error": str(e),
            }


role_architect = RoleArchitect()
