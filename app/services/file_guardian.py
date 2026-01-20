# app/services/file_guardian.py
import logging
import io
import json
import re
from typing import Optional
from fastapi import UploadFile, HTTPException
from app.db import supabase
from app.services.safe_logger import safe_logger
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
from litellm import acompletion # OpenAI Bridge

# 🧠 Importaciones para la Inteligencia Artificial Local
try:
    from transformers import pipeline
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

logger = logging.getLogger("agentshield.file_guardian")

class FileGuardian:
    """
    Guardián Híbrido Dual:
    - Modo A (Soberano): Regex + IA Local (CPU). Privacidad máxima.
    - Modo B (Cloud): Regex + OpenAI (GPT-4). Precisión máxima.
    Configurable por Tenant.
    """
    
    def __init__(self):
        self.classifier = None
        self.ai_available_local = False
        
        # 1. Intentar cargar IA Local (Siempre disponible como fallback o modo soberano)
        if AI_AVAILABLE:
            try:
                logger.info("🛡️ Inicializando Smart Guardian Local (Modelo NLI en CPU)...")
                # Modelo ultra-ligero (40MB) para clasificación Zero-Shot rápida
                self.classifier = pipeline(
                    "zero-shot-classification",
                    model="valhalla/distilbart-mnli-12-1",
                    device=-1 # Forzar CPU
                )
                self.ai_available_local = True
            except Exception as e:
                logger.warning(f"⚠️ No se pudo cargar modelo Local: {e}. Solo disponible modo Regex o OpenAI.")

        # Patrones "Gatillo"
        self.regex_triggers = {
            "INVOICE": [r"(?i)factura", r"(?i)invoice", r"(?i)iban", r"(?i)swift", r"(?i)total\s*a\s*pagar"],
            "HR_DATA": [r"(?i)nómina", r"(?i)salario", r"(?i)confidencial", r"(?i)dni", r"(?i)passport"],
            "FINANCIAL_REPORT": [r"(?i)p&l", r"(?i)balance\s*sheet", r"(?i)ganancias", r"(?i)pérdidas"]
        }

    async def inspect_and_filter(self, file: UploadFile, user_id: str, tenant_id: str, dept_id: Optional[str] = None):
        if not file.filename:
            return True
            
        filename = file.filename
        
        # 1. Leer contenido (Texto o OCR)
        content_sample = await self._read_file_head(file)
        
        # 2. Obtener modo de seguridad del Tenant
        security_mode = await self._get_tenant_security_mode(tenant_id)
        
        # 3. Análisis Inteligente (Pasamos el modo)
        content_category = await self._analyze_content(filename, content_sample, security_mode)
        
        # 4. Enforce
        await self._enforce_policy(tenant_id, dept_id, user_id, filename, content_category, security_mode)
        return True

    async def _get_tenant_security_mode(self, tenant_id: str) -> str:
        """Fetch 'security_config' from tenant. Default: 'LOCAL'."""
        try:
            # En producción, esto debería estar cacheado (Redis)
            res = supabase.table("tenants").select("security_config").eq("id", tenant_id).single().execute()
            if res.data and res.data.get('security_config'):
                return res.data['security_config'].get('ai_mode', 'LOCAL')
        except:
             # Si falla la DB o no existe la columna, default a LOCAL (Privacidad por defecto)
            pass
        return "LOCAL"

    async def _read_file_head(self, file: UploadFile, size=2048) -> str:
        """
        Extracción Inteligente: Texto Digital o Píxeles (OCR).
        """
        content_type = file.content_type
        await file.seek(0)
        file_bytes = await file.read()
        await file.seek(0) # Reset

        text_content = ""

        try:
            # CASO 1: Imágenes (JPG/PNG) -> OCR Directo
            if  content_type and "image" in content_type:
                logger.info(f"📸 Imagen detectada: Ejecutando OCR en {file.filename}")
                image = Image.open(io.BytesIO(file_bytes))
                text_content = pytesseract.image_to_string(image)

            # CASO 2: PDF -> Intentar texto digital, si falla, OCR
            elif content_type and "pdf" in content_type:
                try:
                    # Intento rápido (pypdf o similar)
                    import PyPDF2
                    pdf = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    text_content = ""
                    for page in pdf.pages[:2]: # Solo primeras 2 páginas
                        text_content += page.extract_text() or ""
                except:
                     pass
                
                # Si el PDF está escaneado (vacío de texto), renderizamos a imagen y OCR
                if len(text_content) < 50: 
                    logger.info("📄 PDF Escaneado detectado: Activando OCR de emergencia...")
                    # Requiere poppler-utils instalado en el Dockerfile
                    images = convert_from_bytes(file_bytes, first_page=1, last_page=2)
                    for img in images:
                        text_content += pytesseract.image_to_string(img)

            # CASO 3: Texto plano / Código
            else:
                text_content = file_bytes.decode('utf-8', errors='ignore')

        except Exception as e:
            logger.error(f"Error en extracción: {e}")
            return "" # Fail-safe

        # Devolvemos los primeros 2000 caracteres para la IA
        return text_content[:2000]

    async def _analyze_content(self, filename: str, text: str, mode: str = 'LOCAL') -> str:
        """
        Cerebro Dual: Decide si usar Local AI o OpenAI basado en 'mode'.
        """
        # A. Barrido Regex (Siempre activo por performance)
        detected_trigger = None
        for category, patterns in self.regex_triggers.items():
            for pattern in patterns:
                if re.search(pattern, filename) or re.search(pattern, text):
                    detected_trigger = category
                    break
        
        if not detected_trigger:
            return "GENERIC"

        # B. Verificación IA
        logger.info(f"🔍 Security Check triggered for '{filename}'. Mode: {mode}")

        # MODO CLOUD (GPT-4) - Precisión Total
        if mode == "OPENAI":
             return await self._semantic_verify_openai(filename, text, detected_trigger)

        # MODO LOCAL (Soberano) - Privacidad Total
        if self.ai_available_local and self.classifier:
             return self._semantic_verify_local(filename, text, detected_trigger)
             
        # Fallback (Si Local falla o no está disponible)
        return detected_trigger

    def _semantic_verify_local(self, filename: str, text: str, category: str) -> str:
        """Inferencia CPU Local"""
        snippet = text[:1000]
        if category == "INVOICE":
            labels = ["actual invoice with payment details", "educational document about invoicing", "software configuration"]
            target_label = "actual invoice with payment details"
        elif category == "HR_DATA":
             labels = ["private employee personal data", "public hr policy", "resume template"]
             target_label = "private employee personal data"
        else:
             return category

        try:
            result = self.classifier(snippet, labels)
            top_label = result['labels'][0]
            score = result['scores'][0]
            
            logger.info(f"🤖 Local AI Verdict: {top_label} ({score:.2f})")
            
            if top_label == target_label and score > 0.6:
                return category
                
            return "GENERIC"
        except Exception as e:
            logger.error(f"Local AI Error: {e}")
            return category # Fail Safe

    async def _semantic_verify_openai(self, filename: str, text: str, category: str) -> str:
        """Consulta a GPT-4o"""
        snippet = text[:2000]
        
        system_prompt = f"""
        You are a Data Loss Prevention (DLP) determination engine.
        Category to Detect: {category}
        Rules:
        - If it looks like a real invoice/salary/report: RETURN "VIOLATION"
        - If it is a policy document or code: RETURN "SAFE"
        Respond ONLY with JSON: {{"verdict": "VIOLATION" | "SAFE", "confidence": float, "reason": "string"}}
        """
        
        try:
            response = await acompletion(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"FILENAME: {filename}\n\nCONTENT:\n{snippet}"}
                ],
                response_format={ "type": "json_object" }
            )
            
            content = response.choices[0].message.content
            result = json.loads(content)
            
            logger.info(f"🤖 OpenAI Verdict: {result['verdict']} ({result['reason']})")
            
            if result['verdict'] == "VIOLATION":
                return category
            
            return "GENERIC"
            
        except Exception as e:
            logger.error(f"OpenAI Verification Failed: {e}")
            return category

    async def _enforce_policy(self, tenant_id, dept_id, user_id, filename, category, mode):
        """Aplica la lógica de bloqueo consultando la DB."""
        try:
            res = supabase.table("policies")\
                .select("id, name, rules, mode, target_dept_id")\
                .eq("tenant_id", tenant_id)\
                .eq("action", "BLOCK_UPLOAD")\
                .eq("is_active", True)\
                .execute()
            
            policies = res.data or []

            for policy in policies:
                p_dept = policy.get('target_dept_id')
                if p_dept and str(p_dept) != str(dept_id):
                    continue 

                rules = policy.get('rules', {})
                
                # REGLA 1: Contenido Semántico Prohibido
                if category in rules.get('block_categories', []):
                    reason = f"Contenido sensible: {category}. Verificado por {mode} AI."
                    await self._audit_block(tenant_id, policy['id'], user_id, filename, category, reason, mode)
                    
                    if policy.get('mode') == 'ENFORCE':
                        raise HTTPException(403, f"⛔ Security Block: {category} detectado ({mode} Mode).")

                # REGLA 2: Extensión de Archivo
                ext = filename.split('.')[-1].lower() if '.' in filename else ''
                allowed = rules.get('allowed_extensions', [])
                if allowed and ext not in allowed:
                    reason = f"Extensión .{ext} no permitida"
                    await self._audit_block(tenant_id, policy['id'], user_id, filename, category, reason, mode)
                    if policy.get('mode') == 'ENFORCE':
                        raise HTTPException(403, f"⛔ Bloqueado: Tipo de archivo .{ext} no permitido.")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error aplicando políticas: {e}")
            raise HTTPException(500, "Error verificando políticas de seguridad.")

    async def _audit_block(self, tenant_id, policy_id, user_id, filename, category, reason, mode):
        """Registra el evento en el log de auditoría."""
        try:
            supabase.table("policy_events").insert({
                "tenant_id": tenant_id,
                "policy_id": policy_id,
                "event_type": "FILE_UPLOAD_BLOCKED",
                "action_taken": "BLOCKED",
                "user_id": user_id,
                "metadata": {
                    "filename": filename,
                    "category": category,
                    "reason": reason,
                    "ai_mode": mode
                },
                "created_at": "now()"
            }).execute()
        except Exception as e:
            logger.error(f"Fallo en auditoría: {e}")

file_guardian = FileGuardian()
