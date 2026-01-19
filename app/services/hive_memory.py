# app/services/hive_memory.py
from app.services.reranker import get_embedding 
from app.db import supabase
import logging

logger = logging.getLogger("agentshield.hive")

async def search_hive_mind(tenant_id: str, query_text: str, similarity_threshold=0.85):
    """
    Busca si ALGUIEN en la empresa ya resolvió este problema antes.
    """
    if not query_text or not isinstance(query_text, str):
        return None

    emb = await get_embedding(query_text)
    if not emb:
        return None
    
    try:
        # RPC call a Supabase (debes crear la función match_hive_interactions en SQL)
        # Note: Supabase-py execute() is sync, wrapping in potential future async logic
        res = supabase.rpc("match_hive_interactions", {
            "query_embedding": emb,
            "match_threshold": similarity_threshold,
            "match_count": 1,
            "filter_tenant": tenant_id
        }).execute()
        
        if res.data and len(res.data) > 0:
            best_match = res.data[0]
            logger.info(f"🧠 HIVE HIT: Found solution from user {best_match.get('user_email')}")
            return best_match
    except Exception as e:
        logger.warning(f"Hive Search Failed: {e}")
        
    return None

async def store_successful_interaction(tenant_id: str, user_email: str, prompt: str, response: str):
    """
    Guarda una interacción exitosa en la memoria colectiva.
    """
    if not prompt or not response:
        return

    try:
        emb = await get_embedding(prompt)
        if not emb:
            return

        data = {
            "tenant_id": tenant_id,
            "user_email": user_email, # Para dar crédito/Royalties
            "prompt": prompt,
            "response": response,
            "embedding": emb,
            "upvotes": 1 # Empieza con 1
        }
        
        supabase.table("hive_memory").insert(data).execute()
        logger.info(f"🐝 Hive Memory Updated: {user_email} added knowledge.")
    except Exception as e:
        logger.error(f"Failed to store in Hive: {e}")
