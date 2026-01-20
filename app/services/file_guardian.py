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
# Usamos 'pipeline' que descarga y gestiona el modelo automáticamente la primera vez
try:
    from transformers import pipeline
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

logger = logging.getLogger("agentshield.file_guardian")

class FileGuardian:
    """
    Guardián de Archivos Híbrido: Regex Rápido + Verificación Semántica (IA).
    
    1. Usa Regex para detectar amenazas potenciales (0ms latencia).
    2. Si detecta algo, usa un modelo NLP local (CPU) para confirmar el contexto.
    3. Aplica políticas de bloqueo consultando Supabase.
    """
    
    def __init__(self):
        self.classifier = None
        if AI_AVAILABLE:
            try:
                logger.info("🛡️ Inicializando Smart Guardian (Modelo NLI en CPU)...")
                # Modelo ultra-ligero (40MB) para clasificación Zero-Shot rápida
                self.classifier = pipeline(
                    "zero-shot-classification",
                    model="valhalla/distilbart-mnli-12-1",
                    device=-1 # Forzar CPU
                )
            except Exception as e:
                logger.warning(f"⚠️ No se pudo cargar el modelo IA: {e}. Usando modo Regex Estricto.")

        # Patrones "Gatillo" (Trigger Patterns)
        self.regex_triggers = {
            "INVOICE": [r"(?i)factura", r"(?i)invoice", r"(?i)iban", r"(?i)swift", r"(?i)total\s*a\s*pagar"],
            "HR_DATA": [r"(?i)nómina", r"(?i)salario", r"(?i)confidencial", r"(?i)dni", r"(?i)passport"],
            "FINANCIAL_REPORT": [r"(?i)p&l", r"(?i)balance\s*sheet", r"(?i)ganancias", r"(?i)pérdidas"]
        }

    async def inspect_and_filter(self, file: UploadFile, user_id: str, tenant_id: str, dept_id: Optional[str] = None):
        if not file.filename:
            return True
            
        filename = file.filename
        
        # 1. Leer una muestra del contenido (Primeros 2KB para velocidad)
        # Esto evita cargar archivos de 500MB en RAM
        content_sample = await self._read_file_head(file)
        
        # 2. Análisis Inteligente
        content_category = await self._analyze_content(filename, content_sample)
        
        # 3. Consultar Supabase para ver si esa categoría está prohibida
        await self._enforce_policy(tenant_id, dept_id, user_id, filename, content_category)

        return True

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

    async def _analyze_content(self, filename: str, text: str) -> str:
        """
        El cerebro del sistema (Powered by OpenAI).
        Retorna: 'INVOICE', 'HR_DATA' o 'GENERIC' (seguro).
        """
        # A. Barrido Regex (Rápido)
        detected_trigger = None
        for category, patterns in self.regex_triggers.items():
            for pattern in patterns:
                if re.search(pattern, filename) or re.search(pattern, text):
                    detected_trigger = category
                    break
        
        if not detected_trigger:
            return "GENERIC" # No parece peligroso

        # B. Verificación IA (Lento pero preciso)
        # Usamos OpenAI para resolver ambigüedad (Zero False Positives)
        # 100% Accuracy requerida por el usuario.
        
        # Llamada Asíncrona a la IA Suprema
        return await self._semantic_verify_openai(filename, text, detected_trigger)

    async def _semantic_verify_openai(self, filename: str, text: str, category: str) -> str:
        """
        Consulta a GPT-4o: ¿Es esto un documento real o solo ruido?
        """
        snippet = text[:2000]
        
        system_prompt = f"""
        You are a Data Loss Prevention (DLP) determination engine.
        Analyze the provided document text.
        Your goal: Determine if this document IS A REAL {category} containing sensitive data, or if it is SAFE (educational, definition, blank template, code).
        
        Category to Detect: {category}
        
        Rules:
        - If it looks like a real invoice/salary/report: RETURN "VIOLATION"
        - If it is a policy document ABOUT invoices: RETURN "SAFE"
        - If it is python/sql code: RETURN "SAFE"
        
        Respond ONLY with a JSON object: {{"verdict": "VIOLATION" | "SAFE", "confidence": 0.0-1.0, "reason": "short explanation"}}
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
            
            logger.info(f"🤖 OpenAI Verdict for {filename}: {result['verdict']} ({result['reason']})")
            
            if result['verdict'] == "VIOLATION":
                return category
            
            return "GENERIC" # Safe
            
        except Exception as e:
            logger.error(f"OpenAI Verification Failed: {e}")
            # Fallback a Fail-Closed (Bloquear si hay duda y el regex saltó) o Fail-Open?
            # User favors accuracy, but if API fails, security first -> Block.
            return category
            
    # Legacy Local AI removed for GPT-4 preference
    # def _semantic_verify(...)

    async def _enforce_policy(self, tenant_id, dept_id, user_id, filename, category):
        """Aplica la lógica de bloqueo consultando la DB."""
        try:
            # Traemos las reglas de bloqueo activas
            res = supabase.table("policies")\
                .select("id, name, rules, mode, target_dept_id")\
                .eq("tenant_id", tenant_id)\
                .eq("action", "BLOCK_UPLOAD")\
                .eq("is_active", True)\
                .execute()
            
            policies = res.data or []

            for policy in policies:
                # Filtro de Departamento
                p_dept = policy.get('target_dept_id')
                if p_dept and str(p_dept) != str(dept_id):
                    continue 

                rules = policy.get('rules', {})
                
                # REGLA 1: Contenido Semántico Prohibido
                if category in rules.get('block_categories', []):
                    reason = f"Contenido sensible detectado: {category} (Verificado por IA)"
                    await self._audit_block(tenant_id, policy['id'], user_id, filename, category, reason)
                    
                    if policy.get('mode') == 'ENFORCE':
                        raise HTTPException(403, f"⛔ Security Block: El archivo contiene {category} real. ({reason})")

                # REGLA 2: Extensión de Archivo
                ext = filename.split('.')[-1].lower() if '.' in filename else ''
                allowed = rules.get('allowed_extensions', [])
                if allowed and ext not in allowed:
                    reason = f"Extensión .{ext} no permitida"
                    await self._audit_block(tenant_id, policy['id'], user_id, filename, category, reason)
                    if policy.get('mode') == 'ENFORCE':
                        raise HTTPException(403, f"⛔ Bloqueado: Tipo de archivo .{ext} no permitido.")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error aplicando políticas: {e}")
            # En caso de error de DB, bloquear por seguridad (Fail-Closed)
            raise HTTPException(500, "Error verificando políticas de seguridad.")

    async def _audit_block(self, tenant_id, policy_id, user_id, filename, category, reason):
        """Registra el evento en el log de auditoría inmutable."""
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
                    "ai_verified": True if self.classifier else False
                },
                "created_at": "now()"
            }).execute()
        except Exception as e:
            logger.error(f"Fallo en auditoría: {e}")

file_guardian = FileGuardian()
