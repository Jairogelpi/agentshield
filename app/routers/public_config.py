from fastapi import APIRouter, HTTPException, Request
from app.db import supabase, redis_client
import json
import logging

logger = logging.getLogger("agentshield.public")

router = APIRouter(tags=["Public Config"])

@router.get("/v1/public/tenant-config")
async def get_tenant_config(request: Request, domain: str = None):
    """
    Endpoint PÚBLICO (sin auth) que devuelve solo datos de marca.
    Usa caché agresivo porque esto se llama en cada carga de página.
    """
    # ZERO-TOUCH: Si no envían 'domain' explícito, usamos el Host header.
    # Esto permite que 'chat.cliente.com' funcione sin configuración.
    if not domain:
        host = request.headers.get("host", "")
        # Limpiar puerto si existe (ej: localhost:3000 -> localhost)
        domain = host.split(":")[0] 
        
    try:
    try:
        # 1. Check Redis Cache (Critical for performance)
        cache_key = f"tenant_config:{domain}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        # 2. Lookup DB
        # Buscamos por custom_domain
        # Simplificación: Asumimos 'custom_domain' es único y correcto
        res = supabase.table("tenants")\
            .select("id, name, brand_config, sso_config, custom_domain")\
            .eq("custom_domain", domain)\
            .execute()

        data = res.data[0] if res.data else None

        if not data:
            # Fallback al dominio por defecto si no existe
            return {
                "found": False,
                "brand": {
                    "company_name": "AgentShield",
                    "primary_color": "#000000"
                }
            }

        config = {
            "found": True,
            "tenant_id": data['id'],
            "name": data['name'],
            "brand": data['brand_config'],
            "sso": data['sso_config'] # Solo public keys/endpoints, nada secreto
        }

        # 3. Guardar en Caché (1 hora)
        await redis_client.setex(cache_key, 3600, json.dumps(config))
        
        return config
        
    except Exception as e:
        logger.error(f"Tenant config lookup failed: {e}")
        return {"found": False, "error": str(e)}
