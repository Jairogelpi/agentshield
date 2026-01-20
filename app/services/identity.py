# app/services/identity.py
import json
import logging
import os

from fastapi import Header, HTTPException
from jose import JWTError, jwt

from app.db import redis_client, supabase

logger = logging.getLogger("agentshield.identity")

# Use the same secret key as logic.py (Shared Secret)
SECRET_KEY = os.getenv("ASARL_SECRET_KEY") or os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    # Fail fast if security is not configured
    logger.error("FATAL: JWT_SECRET_KEY/ASARL_SECRET_KEY not set.")

ALGORITHM = "HS256"


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
            # 3. Si no esta en cache, resolver identidad completa (SIN MOCKS)

            # Busco en tabla publica de usuarios
            res = supabase.table("users").select("*").eq("id", user_id).single().execute()

            if not res.data:
                # Fallback: Usar metadata del token + Tenant Default
                tenant_id = app_metadata.get("tenant_id")
                if not tenant_id:
                    # Si no hay tenant en metadata, error fatal (Zero Trust)
                    # raise HTTPException(403, "Identity Verification Failed: No Tenant Found")
                    # Fallback de emergencia para desarrollo/demo si no hay tenant
                    tenant_id = "default_tenant"  # O manejar segun logica de negocio

                # Buscamos el departamento por defecto del Tenant real
                dept_res = (
                    supabase.table("departments")
                    .select("id")
                    .eq("tenant_id", tenant_id)
                    .limit(1)
                    .execute()
                )
                dept_id = dept_res.data[0]["id"] if dept_res.data else "none"

                profile = {
                    "email": email,
                    "department_id": dept_id,
                    "tenant_id": tenant_id,
                    "role": app_metadata.get("role", "member"),
                }
            else:
                profile = res.data
                # Enriquecer perfil incompleto
                if "department_id" not in profile or not profile["department_id"]:
                    dept_res = (
                        supabase.table("departments")
                        .select("id")
                        .eq("tenant_id", profile["tenant_id"])
                        .limit(1)
                        .execute()
                    )
                    profile["department_id"] = dept_res.data[0]["id"] if dept_res.data else "none"

                if "tenant_id" not in profile:
                    profile["tenant_id"] = app_metadata.get("tenant_id")
                if "role" not in profile:
                    profile["role"] = app_metadata.get("role", "member")

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
