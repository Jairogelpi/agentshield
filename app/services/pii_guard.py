# app/services/pii_guard.py
import os
import logging
import asyncio
import numpy as np
import time
from litellm import completion

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
                logger.error(f"Local PII Inference Failed: {e}. Switching to Cloud Fallback.")
        
        # B. FALLBACK CLOUD (API)
        # Solo usamos esto si TODO lo demás falla o no está disponible.
        if not engine and len(text) > 0 and "API" in PII_MODEL_API: 
             system_prompt = (
                "You are a PII Redaction Engine. Your ONLY job is to replace sensitive Personal Identifiable Information "
                "(Names, Locations, IDs, Secrets) with placeholders. Return ONLY the redacted text."
             )
             try:
                with tracer.start_as_current_span("pii_cloud_fallback_sync"):
                    response = completion(
                        model=PII_MODEL_API,
                        messages=[
                             {"role": "system", "content": system_prompt},
                             {"role": "user", "content": text}
                        ],
                        temperature=0.0
                    )
                    return response.choices[0].message.content
             except Exception as api_err:
                 logger.error(f"Cloud PII Fallback Failed: {api_err}")
                 
        return text

async def advanced_redact_pii(text: str, tenant_id: str = "unknown") -> str:
    """
    Wrapper Async para mantener compatibilidad con codigo existente (Proxy, etc).
    Offloadea la version sincrona a un thread para no bloquear el Event Loop.
    """
    return await asyncio.to_thread(redact_pii_sync, text, tenant_id)

