# app/services/file_guardian.py
import logging
import io
import json
import re
import hashlib
from typing import Optional, Tuple
from fastapi import UploadFile, HTTPException
from app.db import supabase
from app.services.safe_logger import safe_logger
from app.webhooks import trigger_webhook
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes
from litellm import acompletion 

try:
    from transformers import pipeline
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

logger = logging.getLogger("agentshield.file_guardian")

class FileGuardian:
    """
    Guardián Híbrido Dual + HITL (Quarentine):
    - Whitelist: Memoria activa (0ms).
    - Traffic Light: Red (Block), Yellow (Quarantine), Green (Pass).
    - Modes: Local vs Cloud AI.
    """
    
    def __init__(self):
        self.classifier = None
        self.ai_available_local = False
        
        if AI_AVAILABLE:
            try:
                logger.info("🛡️ Inicializando Smart Guardian Local (CPU)...")
                self.classifier = pipeline(
                    "zero-shot-classification",
                    model="valhalla/distilbart-mnli-12-1",
                    device=-1
                )
                self.ai_available_local = True
            except Exception as e:
                logger.warning(f"⚠️ Local AI Load Failed: {e}")

        self.regex_triggers = {
            "INVOICE": [r"(?i)factura", r"(?i)invoice", r"(?i)iban", r"(?i)swift", r"(?i)total\s*a\s*pagar"],
            "HR_DATA": [r"(?i)nómina", r"(?i)salario", r"(?i)confidencial", r"(?i)dni", r"(?i)passport"],
            "FINANCIAL_REPORT": [r"(?i)p&l", r"(?i)balance\s*sheet", r"(?i)ganancias", r"(?i)pérdidas"]
        }

    async def inspect_and_filter(self, file: UploadFile, user_id: str, tenant_id: str, dept_id: Optional[str] = None):
        if not file.filename: return True
        
        # 1. HASHING (Huella Digital)
        await file.seek(0)
        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()
        await file.seek(0) # Reset para OCR

        # 2. CHECK WHITELIST (Active Learning)
        if await self._is_whitelisted(file_hash, tenant_id):
            logger.info(f"✅ Whitelisted File Detected ({file_hash[:8]}). Bypassing AI.")
            return True 

        # 3. LEER Y ANALIZAR
        content_sample = await self._read_file_head(file)
        security_mode = await self._get_tenant_security_mode(tenant_id)
        
        # Obtenemos Categoría Y Confianza
        category, confidence = await self._analyze_content(file.filename, content_sample, security_mode)

        # 4. TRÁFICO Y SEMÁFORO
        if category != "GENERIC":
            # 🔴 ROJO: Alta Confianza (>90%) -> BLOQUEO
            if confidence > 0.90:
                reason = f"High Confidence Threat ({confidence:.2f}). Mode: {security_mode}"
                await self._enforce_policy_block(tenant_id, dept_id, user_id, file.filename, category, reason, security_mode)

            # 🟡 AMARILLO: Zona de Duda (40% - 90%) -> CUARENTENA
            elif confidence > 0.40:
                logger.warning(f"⚠️ Ambiguous Content ({confidence:.2f}). Sending to Quarantine.")
                await self._send_to_quarantine(tenant_id, user_id, file.filename, file_hash, category, confidence)
                
                # Lanzamos 202 Accepted para que el Frontend sepa que está "En Revisión"
                raise HTTPException(
                    status_code=202, 
                    detail="⚠️ File in Quarantine: AI detected potential risk. Admin approval required."
                )

        # 🟢 VERDE: Confianza baja o Genérico -> PASA
        return True

    async def _is_whitelisted(self, file_hash: str, tenant_id: str) -> bool:
        """Chequea si el admin ya aprobó este archivo."""
        try:
            res = supabase.table("semantic_whitelist")\
                .select("file_hash")\
                .eq("tenant_id", tenant_id)\
                .eq("file_hash", file_hash)\
                .maybe_single()\
                .execute()
            return bool(res.data)
        except:
             return False

    async def _send_to_quarantine(self, tenant_id, user_id, filename, file_hash, category, confidence):
        """Persiste en cola y notifica."""
        try:
            supabase.table("quarantine_queue").insert({
                "tenant_id": tenant_id,
                "user_id": user_id, 
                "file_name": filename,
                "file_hash": file_hash,
                "detected_category": category,
                "ai_confidence": confidence,
                "status": "PENDING"
            }).execute()
            
            # Notificación al Admin
            await trigger_webhook(tenant_id, "security.quarantine", {
                "filename": filename,
                "confidence": confidence,
                "category": category
            })
        except Exception as e:
            logger.error(f"Failed to quarantine: {e}")

    async def _get_tenant_security_mode(self, tenant_id: str) -> str:
        try:
            res = supabase.table("tenants").select("security_config").eq("id", tenant_id).single().execute()
            if res.data and res.data.get('security_config'):
                return res.data['security_config'].get('ai_mode', 'LOCAL')
        except: pass
        return "LOCAL"

    async def _read_file_head(self, file: UploadFile, size=2048) -> str:
        # (Lógica OCR idéntica a versión anterior)
        content_type = file.content_type
        await file.seek(0)
        file_bytes = await file.read()
        await file.seek(0)
        text_content = ""
        try:
            if content_type and "image" in content_type:
                image = Image.open(io.BytesIO(file_bytes))
                text_content = pytesseract.image_to_string(image)
            elif content_type and "pdf" in content_type:
                import PyPDF2
                try:
                    pdf = PyPDF2.PdfReader(io.BytesIO(file_bytes))
                    for page in pdf.pages[:2]: text_content += page.extract_text() or ""
                except: pass
                if len(text_content) < 50:
                    images = convert_from_bytes(file_bytes, first_page=1, last_page=2)
                    for img in images: text_content += pytesseract.image_to_string(img)
            else:
                text_content = file_bytes.decode('utf-8', errors='ignore')
        except: return ""
        return text_content[:2000]

    async def _analyze_content(self, filename: str, text: str, mode: str) -> Tuple[str, float]:
        """Devuelve (Category, Confidence Score)"""
        detected_trigger = None
        for category, patterns in self.regex_triggers.items():
            for pattern in patterns:
                if re.search(pattern, filename) or re.search(pattern, text):
                    detected_trigger = category
                    break
        
        if not detected_trigger: return ("GENERIC", 0.0)

        logger.info(f"🔍 Analyzing '{filename}' [{mode}] Trigger: {detected_trigger}")

        if mode == "OPENAI":
             return await self._semantic_verify_openai(filename, text, detected_trigger)

        if self.ai_available_local and self.classifier:
             return self._semantic_verify_local(filename, text, detected_trigger)
             
        # Fallback Strict
        return (detected_trigger, 1.0) 

    def _semantic_verify_local(self, filename: str, text: str, category: str) -> Tuple[str, float]:
        snippet = text[:1000]
        # Labels definition...
        if category == "INVOICE": target_label = "actual invoice with payment details"
        elif category == "HR_DATA": target_label = "private employee personal data"
        else: target_label = "sensitive content" 
        
        # Labels completos para Zero-Shot
        labels = [target_label, "harmless document", "public information"]

        try:
            result = self.classifier(snippet, labels)
            top_label = result['labels'][0]
            score = result['scores'][0]
            
            if top_label == target_label:
                return (category, score)
            return ("GENERIC", 0.0)
        except Exception as e:
            logger.error(f"Local AI Error: {e}")
            return (category, 1.0) # Fail safe block

    async def _semantic_verify_openai(self, filename: str, text: str, category: str) -> Tuple[str, float]:
        """Returns (Category, Confidence)"""
        snippet = text[:2000]
        system_prompt = f"""
        You are a DLP engine. Category: {category}.
        Respond JSON: {{"verdict": "VIOLATION" | "SAFE", "confidence": float (0.0-1.0)}}
        """
        try:
            response = await acompletion(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"CONTENT:\n{snippet}"}
                ],
                response_format={ "type": "json_object" }
            )
            result = json.loads(response.choices[0].message.content)
            
            if result['verdict'] == "VIOLATION":
                return (category, float(result.get('confidence', 0.95)))
            
            return ("GENERIC", 0.0)
        except:
            return (category, 1.0) # Fail safe

    async def _enforce_policy_block(self, tenant_id, dept_id, user_id, filename, category, reason, mode):
        # Lógica de bloqueo (extraída de versión anterior)
        # Solo audita y lanza excepción si hay match con policy
        try:
            res = supabase.table("policies").select("*").eq("tenant_id", tenant_id).eq("action", "BLOCK_UPLOAD").execute()
            policies = res.data or []
            for policy in policies:
                 # Check dept...
                 # Check category in rules...
                 rules = policy.get('rules', {})
                 if category in rules.get('block_categories', []):
                     await self._audit_block(tenant_id, policy['id'], user_id, filename, category, reason, mode)
                     if policy.get('mode') == 'ENFORCE':
                         raise HTTPException(403, f"⛔ Security Block: {category}")
        except HTTPException: raise
        except: pass

    async def _audit_block(self, tenant_id, policy_id, user_id, filename, category, reason, mode):
        # (Audit Logic standard)
        try:
            supabase.table("policy_events").insert({
                "tenant_id": tenant_id,
                "policy_id": policy_id,
                "event_type": "FILE_UPLOAD_BLOCKED",
                "action_taken": "BLOCKED",
                "user_id": user_id,
                "metadata": {"filename": filename, "category": category, "reason": reason},
                "created_at": "now()"
            }).execute()
        except: pass

file_guardian = FileGuardian()
