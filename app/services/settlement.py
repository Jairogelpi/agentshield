from app.db import supabase
from typing import List
import logging

logger = logging.getLogger("agentshield.settlement")

class SettlementService:
    async def distribute_knowledge_royalties(
        self,
        tenant_id: str, 
        buyer_user_id: str, 
        used_document_ids: List[str], 
        total_cost_of_query: float
    ):
        """
        Distribuye dividendos a los creadores del conocimiento.
        Modelo: El 20% del coste de la query se reparte entre los dueños de los docs usados.
        """
        if not used_document_ids or total_cost_of_query <= 0:
            return

        try:
            royalty_pool = total_cost_of_query * 0.20 # 20% para los creadores
            amount_per_doc = royalty_pool / len(used_document_ids)
            
            # 1. Buscar dueños de los documentos
            # Usamos in_ para filtrar por lista de IDs
            assets = supabase.table("vault_documents")\
                .select("id, uploaded_by, filename")\
                .in_("id", used_document_ids)\
                .execute()
                
            transactions = []
            
            for doc in assets.data:
                owner_id = doc.get('uploaded_by')
                # Regla: No pagarse a sí mismo (wash trading prevention)
                if not owner_id or str(owner_id) == str(buyer_user_id): 
                    continue 
                
                # 2. Regla Anti-Spam: Limitar 10 royalties por doc/día (Anti-Mining)
                # Usamos Redis para contar hits diarios
                try:
                    from app.db import redis_client
                    import datetime
                    
                    key = f"royalty_cap:{owner_id}:{doc['id']}:{datetime.date.today()}"
                    # Incrementa atomically. Si no existe, lo crea con value 1.
                    hits = await redis_client.incr(key)
                    
                    # Primer hit: Setear expiración de 24h para no llenar RAM
                    if hits == 1:
                        await redis_client.expire(key, 86400)
                        
                    if hits > 10:
                        logger.info(f"🚫 Royalty capped for {doc['filename']} (Hit #{hits})")
                        continue
                        
                except Exception as ex:
                    logger.warning(f"Redis anti-gaming check fail: {ex}")
                    # Fail-open: Permitimos el pago para no castigar por fallo de infra
                    pass
                    
                # 3. Generar Transacción (Buyer -> Seller)
                # En un sistema real de wallets, aquí restaríamos del buyer y sumaríamos al seller (Atomic Tx)
                # Aquí registramos el evento en el Ledger para contabilidad futura
                transactions.append({
                    "tenant_id": tenant_id,
                    "from_wallet_id": buyer_user_id, 
                    "to_wallet_id": owner_id,
                    "amount": amount_per_doc,
                    "concept": "KNOWLEDGE_ROYALTY",
                    "asset_id": doc['id']
                })
                
                logger.info(f"💰 Royalty generated: {amount_per_doc:.6f} for {doc['filename']} (Owner: {owner_id})")
                
            if transactions:
                supabase.table("internal_ledger").insert(transactions).execute()
                
        except Exception as e:
            if transactions:
                supabase.table("internal_ledger").insert(transactions).execute()
                
        except Exception as e:
            logger.error(f"Settlement failed: {e}")

    async def settle_knowledge_usage(self, tenant_id: str, buyer_id: str, buyer_dept_id: str, used_docs_metadata: list):
        """
        Ejecuta las transacciones financieras post-RAG para el Marketplace (V2).
        Soporta repartos de beneficios complejos (Revenue Splits).
        """
        transactions = []
        
        for info in used_docs_metadata:
            # Extraemos datos inyectados por el MarketplaceService
            market_data = info.get('_marketplace_info')
            if not market_data: continue
            
            # 1. Calcular Coste Total
            # En una impl real consideraríamos tokens * markup
            cost = float(market_data.get('base_price', 0)) 
            
            if cost <= 0: continue

            try:
                # 2. Buscar Beneficiarios (Revenue Share)
                # ¿Quiénes mantienen esta colección?
                col_id = info.get('collection_id')
                if not col_id: continue

                splits = supabase.table("revenue_splits")\
                    .select("beneficiary_user_id, share_percentage")\
                    .eq("collection_id", col_id)\
                    .execute()
                    
                beneficiaries = splits.data or []
                
                # Si no hay beneficiarios definidos, el dinero va al Departamento dueño
                if not beneficiaries:
                    owner_dept = market_data.get('owner_dept')
                    if owner_dept:
                        transactions.append({
                            "tenant_id": tenant_id,
                            "from_wallet_id": buyer_dept_id, # Paga el Depto Comprador
                            "to_wallet_id": owner_dept, # Cobra el Depto Vendedor
                            "amount": cost,
                            "concept": "KNOWLEDGE_ACCESS_FEE",
                            "asset_id": info.get('id'), # Traceability
                            "metadata": {"doc": info.get('filename')}
                        })
                else:
                    # Reparto Proporcional
                    for ben in beneficiaries:
                        share_pct = float(ben['share_percentage'])
                        amount_share = cost * (share_pct / 100.0)
                        
                        if amount_share > 0:
                             transactions.append({
                                "tenant_id": tenant_id,
                                "from_wallet_id": buyer_dept_id,
                                "to_wallet_id": ben['beneficiary_user_id'], # Cobra el Empleado
                                "amount": amount_share,
                                "concept": "AUTHOR_ROYALTY",
                                "asset_id": info.get('id'),
                                "metadata": {"doc": info.get('filename')}
                            })
            except Exception as e:
                logger.error(f"Failed to calculate split for col {col_id}: {e}")

        # 3. Ejecutar Lote en el Ledger
        if transactions:
            try:
                supabase.table("internal_ledger").insert(transactions).execute()
                logger.info(f"💰 Settled {len(transactions)} marketplace transactions.")
            except Exception as e:
                 logger.error(f"Failed to commit marketplace ledger: {e}")

settlement_service = SettlementService()
