# app/services/legal_expert.py
import logging

from litellm import acompletion

from app.services.vault import vault

logger = logging.getLogger("agentshield.legal_expert")


class LegalExpert:
    """
    🤖 Abogado IA: Conecta eventos técnicos con textos legales reales (RAG).
    """

    async def analyze_compliance_event(
        self, event_type: str, details: dict, framework: str = "GDPR"
    ):
        """
        1. Busca el artículo de la ley relevante para este evento técnico.
        2. Genera una justificación legal formal.
        """
        try:
            # PASO 1: Búsqueda Semántica en la "Biblioteca Legal"
            # Buscamos en el vector store fragmentos de ley relacionados con el evento
            query = f"security measures for {event_type} regarding {details.get('category', 'sensitive data')} protection"

            # Recuperamos los chunks de texto legal real (RAG)
            relevant_laws = await vault.search_legal_docs(query, framework, limit=2)

            if not relevant_laws:
                # Fallback si no hay embeddings cargados
                return f"El sistema aplicó controles preventivos sobre {details.get('category')} alineados con las mejores prácticas de {framework}, aunque no se encontró una cita específica en la base de conocimientos."

            legal_context = "\n".join(
                [f"{doc['legal_article']}: {doc['legal_text']}" for doc in relevant_laws]
            )

            # PASO 2: Redacción Jurídica con GPT-4
            prompt = f"""
            Actúa como un Perito Judicial Tecnológico especializado en {framework}.
            
            HECHO TÉCNICO:
            El sistema AgentShield bloqueó proactivamente la subida de un archivo/dato:
            - Tipo: {details.get("category")}
            - Motivo: {details.get("reason")}
            - Acción: Bloqueo en tiempo real (RAM interception).

            CONTEXTO LEGAL RECUPERADO ({framework}):
            {legal_context}

            TAREA:
            Escribe un párrafo formal y contundente para un informe de auditoría justificando por qué
            esta acción técnica demuestra cumplimiento normativo estricto.
            Debes CITAR EXPLÍCITAMENTE los artículos recuperados en el contexto legal.
            Usa lenguaje jurídico profesional.
            """

            response = await acompletion(
                model="gpt-4o", messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Legal Expert Analysis failed: {e}")
            return f"Error generando análisis legal avanzado: {str(e)}"

    async def recommend_improvements(self, stats: dict):
        """
        Analiza tendencias y sugiere mejoras (Consultoría Automática).
        """
        attacks = stats.get("blocked_attacks", 0)

        if attacks > 100:
            return "⚠️ ALERTA DE RIESGO: Se detectó un volumen inusualmente alto de intentos de fuga de datos (>100). Se recomienda iniciar una campaña de concienciación de seguridad (Phishing/DLP Awareness) para el personal afectado inmediatamente."
        elif attacks > 0:
            return "✅ ESTADO ÓPTIMO: Los controles DLP están funcionando eficazmente. El volumen de incidentes está dentro de los parámetros operativos normales."
        else:
            return (
                "ℹ️ SIN INCIDENTES: No se han registrado intentos de fuga de datos en este periodo."
            )


legal_expert = LegalExpert()
