# app/services/identity.py
import os
import json
from jose import jwt, JWTError
from fastapi import HTTPException, Header
from app.db import supabase, redis_client
import logging

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
        self.dept_id = dept_id      # El "Cost Center" departamental
        self.tenant_id = tenant_id  # La Empresa
        self.role = role            # admin, manager, user

async def verify_identity_envelope(authorization: str = Header(...)) -> VerifiedIdentity:
    """
async def verify_identity_envelope(credentials: HTTPAuthorizationCredentials = Security(security)) -> AgentShieldContext:
    """
    Valida el JWT y retorna un Contexto Estandarizado.
    """
    token = credentials.credentials
    
    try:
            # Asumimos 'users' tiene todo por ahora como simplificación, o usamos 'auth.users' + 'public.users' info
            
            # Buscamos en nuestra tabla publica de usuarios (que deberia estar synced)
            # o directamente consultamos la tabla que tenga department_id.
            
            # NOTE: Dependiendo de tu schema actual, esto puede variar. 
            # Asumimos una tabla 'users' o similar que linkea user_id -> tenant_id, dept_id.
            
            # Intento 1: Tabla 'users'
            res = supabase.table("users").select("*").eq("id", user_id).single().execute()
            
            if not res.data:
                # Si no está en users, buscamos en el Tenant para ver sus políticas base
                tenant_id = app_metadata.get("tenant_id")
                if not tenant_id:
                    raise HTTPException(403, "User has no associated Tenant (Organization)")
                
                # Buscamos el departamento principal del Tenant para no usar mocks
                dept_res = supabase.table("departments").select("id").eq("tenant_id", tenant_id).limit(1).execute()
                dept_id = dept_res.data[0]['id'] if dept_res.data else "none"

                profile = {
                    "email": email,
                    "department_id": dept_id,
                    "tenant_id": tenant_id,
                    "role": app_metadata.get("role", "member")
                }
            else:
                profile = res.data
                # Asegurar campos minimos SIN MOCKS
                if "department_id" not in profile or not profile["department_id"]:
                     # Lookup dinámico si el perfil está incompleto
                     dept_res = supabase.table("departments").select("id").eq("tenant_id", profile["tenant_id"]).limit(1).execute()
                     profile["department_id"] = dept_res.data[0]['id'] if dept_res.data else "none"
                
                if "tenant_id" not in profile:
                     profile["tenant_id"] = app_metadata.get("tenant_id")
                if "role" not in profile:
                     profile["role"] = app_metadata.get("role", "member")

            # Cacheamos la identidad por 5 minutos (Sincronización a tiempo real)
            await redis_client.setex(f"identity:{user_id}", 300, json.dumps(profile))

        return VerifiedIdentity(
            user_id=user_id,
            email=profile.get('email'),
            dept_id=profile.get('department_id'),
            tenant_id=profile.get('tenant_id'),
            role=profile.get('role')
        )

    except JWTError as e:
        logger.warning(f"⛔ Security Alert: Invalid Token Signature detected: {e}")
        raise HTTPException(401, "Digital Signature Verification Failed")
    except Exception as e:
        logger.error(f"Identity Verification Error: {e}")
        raise HTTPException(500, "Internal Identity Error")
