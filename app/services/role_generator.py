# app/services/role_generator.py
import json
import logging
from typing import List

from pydantic import BaseModel

from app.services.llm_gateway import execute_with_resilience

logger = logging.getLogger("agentshield.role_generator")


class GeneratedRole(BaseModel):
    system_persona: str
    allowed_modes: list[str]
    pii_policy: str
    max_tokens: int
    suggested_department: str
    suggested_function: str


class RoleGenerator:
    """
    Usa OpenAI para traducir deseos del cliente en configuraciones técnicas de AgentShield.
    """

    async def generate_from_description(self, description: str, user_id: str) -> GeneratedRole:
        prompt = f"""
        Actúa como un Ingeniero de Seguridad y Prompt Engineer Senior para AgentShield OS.
        El cliente quiere crear un rol operativo basado en esta descripción: "{description}"

        Tu tarea es generar la configuración técnica en formato JSON con los siguientes campos:
        1. system_persona: Un prompt de sistema robusto, profesional y seguro.
        2. allowed_modes: Lista extraída de ["agentshield-auto", "agentshield-eco", "agentshield-secure", "agentshield-direct"].
        3. pii_policy: 'REDACT' (estándar) o 'BLOCK' (estricto).
        4. max_tokens: Un entero entre 2000 y 8000.
        5. suggested_department: Nombre del departamento (ej: Sales, HR, Engineering).
        6. suggested_function: Título del puesto (ej: Manager, Analyst, Intern).

        Responde ÚNICAMENTE con el objeto JSON válido.
        """

        # Usamos el gateway para resiliencia y métricas
        response = await execute_with_resilience(
            tier="agentshield-smart",  # Usamos el modelo más listo para generar roles
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

            # Limpiar posibles backticks de markdown
            clean_json = content.strip().replace("```json", "").replace("```", "")
            data = json.loads(clean_json)
            return GeneratedRole(**data)
        except Exception as e:
            logger.error(f"Error parseando el rol generado por IA: {e}")
            # Fallback seguro en caso de fallo de parsing
            return GeneratedRole(
                system_persona="You are a helpful corporate assistant. Follow all security policies.",
                allowed_modes=["agentshield-secure"],
                pii_policy="REDACT",
                max_tokens=2000,
                suggested_department="General",
                suggested_function="Staff",
            )


role_generator = RoleGenerator()
