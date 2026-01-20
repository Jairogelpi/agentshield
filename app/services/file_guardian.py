# app/services/file_guardian.py
import logging
import json
import uuid
from typing import Optional
from fastapi import UploadFile, HTTPException
from app.db import supabase
from app.services.safe_logger import safe_logger # Assuming this exists or using standard logger

logger = logging.getLogger("agentshield.file_guardian")

class FileGuardian:
    """
    Guardián de Archivos: Inspecciona uploads y aplica políticas de bloqueo.
    Integrado con Supabase (policies table).
    """
    
    async def inspect_and_filter(self, file: UploadFile, user_id: str, tenant_id: str, dept_id: Optional[str] = None):
        if not file.filename:
            return True
            
        filename = file.filename
        
        # 1. Detección Semántica (Simulada/Mock)
        # En producción, esto usaría OCR o clasificación de texto
        content_category = self._mock_classify_content(filename) 
        
        # 2. Buscar Políticas Activas
        # Buscamos policies ACTION='BLOCK_UPLOAD' para este Tenant
        try:
            # Query Logic: 
            # WHERE tenant_id = X
            # AND action = 'BLOCK_UPLOAD'
            # AND is_active = true
            # AND (target_dept_id IS NULL OR target_dept_id = Y) -> Supabase filter logic slightly limited, handled in code or explicit query
            
            # Fetch all active block rules for this tenant
            res = supabase.table("policies")\
                .select("id, name, rules, mode, target_dept_id")\
                .eq("tenant_id", tenant_id)\
                .eq("action", "BLOCK_UPLOAD")\
                .eq("is_active", True)\
                .execute()
                
            policies = res.data or []
            
            for policy in policies:
                # Filter by Dept: Logic in Memory because OR is tricky in simple Supabase client without raw SQL
                p_dept = policy.get('target_dept_id')
                if p_dept and str(p_dept) != str(dept_id):
                    continue # Policy targets specific dept, and we are not in it
                
                rules = policy.get('rules', {})
                
                # Check 1: Categoría Prohibida
                if content_category in rules.get('block_categories', []):
                    reason = f"Category '{content_category}' Forbidden"
                    await self._audit_block(tenant_id, policy['id'], user_id, filename, content_category, reason)
                    
                    if policy.get('mode') == 'ENFORCE':
                         raise HTTPException(403, f"⛔ Bloqueado por política '{policy['name']}': No se permiten archivos de tipo {content_category}")
                    else:
                        logger.info(f"👻 SHADOW BLOCK: File {filename} matches restriction but mode is SHADOW.")

                # Check 2: Extensión
                ext = filename.split('.')[-1].lower() if '.' in filename else ''
                allowed_exts = rules.get('allowed_extensions', [])
                if allowed_exts and ext not in allowed_exts:
                    reason = f"Extension '.{ext}' Forbidden"
                    await self._audit_block(tenant_id, policy['id'], user_id, filename, content_category, reason)
                    
                    if policy.get('mode') == 'ENFORCE':
                        raise HTTPException(403, f"⛔ Bloqueado por política: Extensión .{ext} no permitida.")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"FileGuardian Inspect Error: {e}")
            # Fail closed or open? Security -> Closed.
            raise HTTPException(500, "Security check failed during file upload.")

        return True

    async def _audit_block(self, tenant_id, policy_id, user_id, filename, category, reason):
        """
        Escribe en tabla 'public.policy_events'
        """
        try:
            event_data = {
                "tenant_id": tenant_id,
                "policy_id": policy_id,
                "event_type": "FILE_UPLOAD_ATTEMPT",
                "action_taken": "BLOCKED",
                "user_id": user_id,
                "metadata": {
                    "filename": filename,
                    "detected_category": category,
                    "reason": reason
                },
                "created_at": "now()" # Let DB handle or isoformat
            }
            supabase.table("policy_events").insert(event_data).execute()
        except Exception as e:
            logger.error(f"Failed to audit block: {e}")

    def _mock_classify_content(self, filename):
        # Simulación de la lógica de clasificación
        lower = filename.lower()
        if "factura" in lower or "invoice" in lower:
            return "INVOICE"
        if "nomina" in lower or "payslip" in lower:
            return "PAYSLIP"
        if "report" in lower and "financial" in lower:
            return "FINANCIAL_REPORT"
        return "GENERIC"

file_guardian = FileGuardian()
