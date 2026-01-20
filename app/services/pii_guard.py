# app/services/pii_guard.py
import os
import logging
import asyncio
import numpy as np
import time
from litellm import completion
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
import agentshield_rust
import onnxruntime as ort

logger = logging.getLogger("agentshield.pii_guard")
tracer = trace.get_tracer(__name__)

# Constants
PII_MODEL_API = os.getenv("PII_MODEL_API", "gpt-3.5-turbo")
PII_MODEL_PATH = os.getenv("PII_MODEL_PATH", "/opt/models/pii_model.onnx")

def fast_regex_scrub(text: str) -> str:
    """Usa el motor de Rust para limpieza ultra-rápida."""
    return agentshield_rust.scrub_pii_fast(text)

class PIIEngine:
    _instance = None
    
    def __init__(self):
        self.session = None
        if os.path.exists(PII_MODEL_PATH):
            try:
                self.session = ort.InferenceSession(PII_MODEL_PATH)
                logger.info(f"✅ PII Local Engine loaded from {PII_MODEL_PATH}")
            except Exception as e:
                logger.error(f"Failed to load PII ONNX model: {e}")

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def predict(self, text: str) -> str:
        # Placeholder for ONNX inference logic
        # Si no hay modelo, devolvemos el texto (la Capa 1 ya hizo el regex)
        return text

def get_pii_engine():
    return PIIEngine.get_instance()

def redact_pii_sync(text: str, tenant_id: str = "unknown") -> str:
    """
    Versión sincrona de la limpieza PII, ideal para llamar desde logging 
    o contextos donde no se puede hacer await.
    """
    with tracer.start_as_current_span("pii_redaction_process_sync") as span:
        span.set_attribute("tenant.id", tenant_id)
        span.set_attribute("text.length", len(text))
        
        # 1. RUST ENGINE (Critical Path)
        start_time = time.perf_counter()
        
        with tracer.start_as_current_span("rust_core_engine") as rust_span:
            # Paso 1: Limpieza Estructural (Rust)
            text = fast_regex_scrub(text)
            
        # Cálculo de latencia técnica
        end_time = time.perf_counter()
        processing_ms = (end_time - start_time) * 1000
        
        # REGISTRO DE MÉTRICA CRÍTICA
        span.set_attribute("pii.rust_processing_time_ms", processing_ms)
        
        # Alerta de degradación
        if processing_ms > 50 and len(text) < 5000:
            span.set_status(Status(StatusCode.ERROR, "High Latency in Rust Engine"))
            span.set_attribute("pii.latency_anomaly", True)

        # Paso 2: Limpieza Semántica (Local VS Cloud)
        # A. INTENTO LOCAL (Sovereign AI)
        engine = get_pii_engine()
        if engine and engine.session:
            try:
                # Ejecución directa sincrona (ONNX Runtime es rápido)
                return engine.predict(text)
            except Exception as e:
                logger.error(f"Local PII Inference Failed: {e}", exc_info=True)
                logger.warning("Switching to Cloud Fallback.")
        
        # B. FALLBACK (Estrategia Competitiva)
        # Si falla la IA local (Rust/ONNX), ¿Bloqueamos 2 segundos para llamar a la nube?
        # Solo si el cliente paga por "Paranoid Mode" (FORCE_CLOUD_FALLBACK).
        # Si no, Regex agresivo es mejor tradeoff (seguro y rápido).
        
        if not engine:
            if os.getenv("FORCE_CLOUD_FALLBACK") == "true":
                logger.warning("⚠️ PII Local Engine not ready. Fallback to Cloud (Slow).")
                # Llamada lenta a LLM externo
                try:
                    response = completion(
                       model=PII_MODEL_API,
                       messages=[{"role": "user", "content": f"Redact PII from this text. Output only redacted text: {text}"}],
                       api_key=os.getenv("PII_API_KEY") 
                    )
                    return response.choices[0].message.content
                except Exception as api_err:
                    logger.error(f"Cloud PII Fallback Failed: {api_err}", exc_info=True)
                    return text # Falla total
            else:
                logger.warning("⚠️ PII Engine not ready. Using Fast Regex Fallback instead of Slow Cloud.")
                # Ya hicimos fast_regex_scrub arriba (Rust/Python Regex), así que devolvemos eso.
                # Evitamos la llamada a completion() que añade latencia oculta.
                return text
                 
        return text

    async def scan(self, messages: list) -> dict:
        """
        Escaneo integral de mensajes.
        Retorna: { "blocked": bool, "changed": bool, "findings_count": int, "cleaned_messages": list }
        """
        cleaned = []
        changed = False
        findings = 0
        
        for m in messages:
            content = m.get("content", "")
            if not isinstance(content, str):
                cleaned.append(m)
                continue
                
            # Capa 1: Rust Scrubbing
            redacted = agentshield_rust.scrub_pii_fast(content)
            
            # Capa 2: Si el texto cambió, registramos hallazgo
            if redacted != content:
                changed = True
                findings += 1
                
            new_m = m.copy()
            new_m["content"] = redacted
            cleaned.append(new_m)
            
        return {
            "blocked": False, # Por defecto no bloqueamos a menos que sea PII crítica (ej: Password)
            "changed": changed,
            "findings_count": findings,
            "cleaned_messages": cleaned
        }

pii_guard = PIIEngine.get_instance()

async def advanced_redact_pii(text: str, tenant_id: str = "unknown") -> str:
    """
    Wrapper Async para mantener compatibilidad con codigo existente (Proxy, etc).
    Offloadea la version sincrona a un thread para no bloquear el Event Loop.
    """
    return await asyncio.to_thread(redact_pii_sync, text, tenant_id)

