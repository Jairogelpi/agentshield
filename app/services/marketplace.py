import logging
from typing import Dict, List, Optional

from app.db import supabase
from app.services import llm_gateway  # Para generar resúmenes si la licencia lo exige
from app.services.identity import VerifiedIdentity

logger = logging.getLogger("agentshield.marketplace")


class MarketplaceService:
    async def enforce_data_license(
        self, identity: VerifiedIdentity, documents: list[dict]
    ) -> list[dict]:
        """
        El núcleo del Marketplace.
        Verifica si el usuario pagó por estos documentos y transforma el contenido
        según la licencia comprada (ej: REDACTAR o RESUMIR).
        """
        processed_docs = []

        # Agrupar documentos por colección para optimizar consultas
        collection_ids = list(
            set(d.get("collection_id") for d in documents if d.get("collection_id"))
        )

        # Obtener licencias activas para este usuario/departamento
        access_map = await self._get_access_rights(identity, collection_ids)

        for doc in documents:
            col_id = doc.get("collection_id")

            # 1. Sin colección = Documento huérfano (Usar reglas default o bloquear)
            if not col_id:
                processed_docs.append(doc)  # Asumimos público/interno por defecto
                continue

            rights = access_map.get(col_id)

            # 2. ACCESO DENEGADO
            if not rights:
                logger.warning(
                    f"🚫 Access Denied: User {identity.email} tried to access collection {col_id} without paying."
                )
                continue  # Omitimos este documento del contexto RAG

            # 3. APLICAR LICENCIA (Transformación al vuelo)
            final_content = doc.get("content", "")

            # Metadata puede ser None, inicializar si es necesario
            if not doc.get("metadata"):
                doc["metadata"] = {}

            if rights["license_type"] == "SUMMARY_ONLY":
                # Generamos un resumen rápido para no revelar el texto exacto
                # (Idealmente esto se cachea)
                final_content = await self._summarize_content(final_content)
                doc["metadata"]["note"] = "⚠️ Licensed Summary Only"

            elif rights["license_type"] == "CITATION_ONLY":
                final_content = f"[Reference to protected document: {doc.get('filename')}]"

            doc["content"] = final_content

            # Adjuntamos info de precio para la liquidación posterior
            doc["_marketplace_info"] = {
                "listing_id": rights["listing_id"],
                "base_price": rights["base_price"],
                "markup": rights["markup"],
                "owner_dept": rights["owner_dept"],
            }

            processed_docs.append(doc)

        return processed_docs

    async def _get_access_rights(self, identity, collection_ids):
        # Consulta SQL compleja para ver suscripciones o listings públicos
        # Retorna dict: { col_id: { license_type: '...', price: ... } }
        if not collection_ids:
            return {}

        try:
            res = supabase.rpc(
                "check_marketplace_access",
                {
                    "p_tenant_id": identity.tenant_id,
                    "p_dept_id": identity.dept_id,
                    "p_collection_ids": collection_ids,
                },
            ).execute()

            return {str(r["collection_id"]): r for r in res.data} if res.data else {}
        except Exception as e:
            logger.error(f"Marketplace access check failed: {e}")
            return {}

    async def _summarize_content(self, text):
        # Usa un modelo rápido (Haiku/GPT-3.5) para ofuscar el original
        messages = [
            {"role": "system", "content": "Summarize strictly. Do not quote."},
            {"role": "user", "content": text},
        ]
        try:
            # Simplificación: Llamada directa a gateway.
            # Necesitamos un user_id dummy o system user execution
            resp = await llm_gateway.execute_with_resilience(
                tier="agentshield-fast", messages=messages, user_id="system-marketplace"
            )
            # Adaptarse a si execute_with_resilience devuelve dict o objeto
            if isinstance(resp, dict):
                return resp["choices"][0]["message"]["content"]
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return "Summary unavailable."


marketplace = MarketplaceService()
