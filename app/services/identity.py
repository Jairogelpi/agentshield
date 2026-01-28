import asyncio
import json
import logging
from fastapi import Header, HTTPException
from jose import JWTError, jwt

from app.config import settings
from app.db import redis_client, supabase

logger = logging.getLogger("agentshield.identity")

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM


class VerifiedIdentity:
    def __init__(self, user_id, email, dept_id, tenant_id, role):
        self.user_id = user_id
        self.email = email
        self.dept_id = dept_id  # El "Cost Center" departamental
        self.tenant_id = tenant_id  # La Empresa
        self.role = role  # admin, manager, user


async def verify_identity_envelope(authorization: str = Header(...)) -> VerifiedIdentity:
    """
    Valida el JWT y retorna un Contexto Estandarizado.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid Authorization Header")

    token = authorization.split(" ")[1]

    try:
        # 1. Decodificar JWT
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        email = payload.get("email")
        app_metadata = payload.get("app_metadata", {})

        if not user_id:
            raise HTTPException(401, "Invalid Token: No Subject")

        # 2. Intentar recuperar identidad desde Redis (Cache)
        cached_profile = await redis_client.get(f"identity:{user_id}")
        if cached_profile:
            profile = json.loads(cached_profile)
        else:
            # 3. Si no esta en cache, resolver identidad completa
            try:
                # Busco en tabla publica de usuarios
                # timeout de 2.0s para no bloquear el login
                res = await asyncio.wait_for(
                    asyncio.to_thread(lambda: supabase.table("users").select("*").eq("id", user_id).single().execute()),
                    timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ Identity resolution timeout for {user_id}")
                raise HTTPException(503, "Identity Service Timeout")

            if not res.data:
                # Fallback: Usar metadata del token
                tenant_id = app_metadata.get("tenant_id")
                if not tenant_id:
                    logger.error(f"❌ Identity Error: No Tenant ID found for user {user_id}")
                    raise HTTPException(403, "Identity Verification Failed: No Tenant Association")

                # Buscamos el departamento por defecto
                try:
                    dept_res = await asyncio.wait_for(
                        asyncio.to_thread(lambda: supabase.table("departments").select("id").eq("tenant_id", tenant_id).limit(1).execute()),
                        timeout=2.0
                    )
                except asyncio.TimeoutError:
                    dept_res = None
                
                dept_id = dept_res.data[0]["id"] if dept_res and dept_res.data else None
                if not dept_id:
                     logger.warning(f"⚠️ User {user_id} has no department in tenant {tenant_id}")

                profile = {
                    "email": email,
                    "department_id": dept_id,
                    "tenant_id": tenant_id,
                    "role": app_metadata.get("role", settings.DEFAULT_ROLE),
                }
            else:
                profile = res.data
                # Enriquecer perfil incompleto
                if "department_id" not in profile or not profile["department_id"]:
                    try:
                        dept_res = await asyncio.wait_for(
                            asyncio.to_thread(lambda: supabase.table("departments").select("id").eq("tenant_id", profile["tenant_id"]).limit(1).execute()),
                            timeout=2.0
                        )
                    except asyncio.TimeoutError:
                        dept_res = None
                    profile["department_id"] = dept_res.data[0]["id"] if dept_res and dept_res.data else None

                if "tenant_id" not in profile:
                    profile["tenant_id"] = app_metadata.get("tenant_id")
                if "role" not in profile:
                    profile["role"] = app_metadata.get("role", settings.DEFAULT_ROLE)

            # Cachear Identidad Verificada (5 min)
            await redis_client.setex(f"identity:{user_id}", 300, json.dumps(profile))

        return VerifiedIdentity(
            user_id=user_id,
            email=profile.get("email"),
            dept_id=profile.get("department_id"),
            tenant_id=profile.get("tenant_id"),
            role=profile.get("role"),
        )

    except JWTError as e:
        logger.warning(f"⛔ Security Alert: Invalid Token Signature detected: {e}")
        raise HTTPException(401, "Digital Signature Verification Failed")
    except Exception as e:
        logger.error(f"Identity Verification Error: {e}")
        raise HTTPException(500, "Internal Identity Error")
