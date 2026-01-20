# app/services/file_guardian.py
import logging
import json
import re
from typing import Optional
from fastapi import UploadFile, HTTPException
from app.db import supabase
from app.services.safe_logger import safe_logger

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
        content_category = self._analyze_content(filename, content_sample)
        
        # 3. Consultar Supabase para ver si esa categoría está prohibida
        await self._enforce_policy(tenant_id, dept_id, user_id, filename, content_category)

        return True

    async def _read_file_head(self, file: UploadFile, size=2048) -> str:
        """Lee el inicio del archivo de forma segura."""
        await file.seek(0)
        data = await file.read(size)
        await file.seek(0) # Resetear puntero imprescindible
        try:
            return data.decode('utf-8', errors='ignore')
        except:
            return ""

    def _analyze_content(self, filename: str, text: str) -> str:
        """
        El cerebro del sistema.
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
        # Si no tenemos IA cargada, nos fiamos del Regex (Fail-Closed)
        if not self.classifier:
            return detected_trigger

        # Preguntamos a la IA: ¿Cuál es la intención real?
        # Definimos hipótesis contradictorias
        if detected_trigger == "INVOICE":
            labels = ["actual invoice with payment details", "educational document about invoicing", "software configuration"]
            target_label = "actual invoice with payment details"
        elif detected_trigger == "HR_DATA":
            labels = ["private employee personal data", "public hr policy", "resume template"]
            target_label = "private employee personal data"
        else:
            return detected_trigger

        # Clasificamos
        result = self.classifier(text[:1000], labels) # Analizamos solo el texto, no el nombre
        top_label = result['labels'][0]
        score = result['scores'][0]

        logger.info(f"🤖 IA Análisis para '{filename}': {top_label} ({score:.2f})")

        # Solo bloqueamos si la IA está >60% segura de que es DATOS REALES
        if top_label == target_label and score > 0.6:
            return detected_trigger
        
        # Si la IA dice que es "educational document", lo dejamos pasar
        logger.info(f"✅ Falso Positivo evitado: Regex dijo {detected_trigger}, IA dijo {top_label}")
        return "GENERIC"

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
