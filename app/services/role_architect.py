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
        # [MODIFIED] Upgrade to God Tier Persona Generation
        prompt = f"""
        Act as an expert AI Behavioral Designer.
        Create a 'Deep System Persona' for a corporate employee with this Job Description:
        "{description}"

        Output strictly valid JSON with keys:
        - department: Suggested department name (e.g. "Legal", "Engineering").
        - function: Suggested job title (e.g. "Senior Counsel").
        - system_persona: A dense, 4-5 sentence directive defining their authority, expertise, and interaction model.
        - cognitive_framework: A specific instruction on how to reason. (e.g., for Legal: "Prioritize risk mitigation over speed. Assume worst-case interpretation."; for Eng: "Prioritize efficiency and technically correct specificity.")
        - tone_guidelines: A list of 3 adjectives (e.g., "Rigorous", "Litigious", "Concise").
        - communication_constraints: 2 rules on how NOT to speak (e.g., "Never use emojis", "Never speculate on facts").
        - pii_policy: "BLOCK" (if sensitive like HR/Finance) or "REDACT" (standard).
        - default_mode: "agentshield-secure" (default) or "agentshield-auto".
        - active_rules: List of 3-5 short security rules (e.g. "No Financial Advice", "DLP Active").

        Ensure the 'system_persona' incorporates the cognitive framework and tone implicitly.
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
                            "cognitive_framework": config.get("cognitive_framework"),
                            "tone_guidelines": config.get("tone_guidelines"),
                            "communication_constraints": config.get("communication_constraints"),
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
