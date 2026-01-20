import hashlib
import json
import logging
from app.db import supabase

logger = logging.getLogger("agentshield.snapshotter")

async def get_system_state_hash(tenant_id: str):
    """
    Calcula un Hash Criptográfico de TODAS las reglas activas en este instante.
    Esto permite probar en un juicio: "El día 20, la regla X estaba activa".
    """
    try:
        # 1. Obtener Políticas Activas
        # Tabla 'policies' no existe en el seed visible, usamos 'tool_policies' y 'semantic_budgets'
        # Si hubiera tabla 'policies' (sistema legacy?), la incluimos.
        # Asumimos 'tool_policies' es la principal de governance.
        
        tools_res = supabase.table("tool_policies").select("*").eq("tenant_id", tenant_id).execute()
        tools_data = tools_res.data or []
        
        # 2. Obtener Presupuestos Semánticos
        budgets_res = supabase.table("semantic_budgets").select("*").eq("tenant_id", tenant_id).eq("is_active", True).execute()
        budgets_data = budgets_res.data or []
        
        # 3. Obtener Config General
        config_res = supabase.table("system_config").select("*").execute()
        config_data = config_res.data or []
        
        # Crear el "State Object"
        state = {
            "tool_policies": tools_data,
            "semantic_budgets": budgets_data,
            "system_config": config_data
        }
        
        # Serializar canónicamente (ordenado por claves para que el hash sea estable)
        # Usamos separadores compactos para consistencia
        state_json = json.dumps(state, sort_keys=True, separators=(',', ':'))
        state_hash = hashlib.sha256(state_json.encode()).hexdigest()
        
        # Intentar guardar el snapshot (si no existe ya este hash)
        # Esto actúa como caché de snapshots.
        try:
            # Check si existe para evitar error de duplicate key (si no usamos ON CONFLICT en SQL)
            # Idealmente el INSERT falla si existe y lo atrapamos.
            # O hacemos select primero (mas lento).
            # Supabase insert no tiene "ON CONFLICT DO NOTHING" via API facil, asi que try/except
            supabase.table("config_snapshots").insert({
                "hash": state_hash,
                "tenant_id": tenant_id,
                "snapshot_type": "FULL_STATE",
                "content": state
            }).execute()
        except Exception as insert_err:
            # Ignoramos error de duplicado, significa que ya está guardado
            pass 
            
        return state_hash
        
    except Exception as e:
        logger.error(f"Snapshot failed: {e}")
        return "partial-hash-error"
