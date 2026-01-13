# app/services/pii_guard.py
import os
import logging
import asyncio
import numpy as np
import time
from litellm import completion

logger = logging.getLogger("agentshield.pii_guard")

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

async def advanced_redact_pii(text: str, tenant_id: str = "unknown") -> str:
    """
    Wrapper Async para mantener compatibilidad con codigo existente (Proxy, etc).
    Offloadea la version sincrona a un thread para no bloquear el Event Loop.
    """
    return await asyncio.to_thread(redact_pii_sync, text, tenant_id)

