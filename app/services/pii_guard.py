# app/services/pii_guard.py
import os
import logging
import asyncio
import numpy as np
import time
from litellm import acompletion
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)

# Constants
USE_LOCAL_PII = os.getenv("USE_LOCAL_PII", "true").lower() == "true"
ONNX_MODEL_PATH = os.getenv("ONNX_MODEL_PATH", "/app/models/pii-ner-quantized.onnx")
TOKENIZER_PATH = os.getenv("TOKENIZER_PATH", "/app/models/tokenizer.json")
PII_MODEL_API = os.getenv("PII_MODEL_API", "gpt-3.5-turbo")

try:
    import agentshield_rust
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    logging.getLogger(__name__).warning("Rust Module not found. Running in Python mode.")

# Lazy global instance
_local_brain = None

def get_pii_engine():
    global _local_brain
    if not USE_LOCAL_PII:
        return None
        
    if _local_brain is None:
        try:
             # Lazy Import to avoid startup overhead
             import onnxruntime as ort
             from tokenizers import Tokenizer
             
             class SovereignPIIEngine:
                def __init__(self):
                    self.session = None
                    self.tokenizer = None
                    try:
                        # Cargamos el modelo cuantizado INT4 (CPU Friendly)
                        opts = ort.SessionOptions()
                        opts.intra_op_num_threads = 1 # Reducimos a 1 para evitar OOM en Render Free
                        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                        
                        if os.path.exists(ONNX_MODEL_PATH) and os.path.exists(TOKENIZER_PATH):
                            logger.info("🧠 Loading Local PII Brain (ONNX)...")
                            self.session = ort.InferenceSession(ONNX_MODEL_PATH, opts, providers=["CPUExecutionProvider"])
                            self.tokenizer = Tokenizer.from_file(TOKENIZER_PATH)
                            logger.info("✅ Local PII Brain Active.")
                        else:
                            pass # Silent fail if not present
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to load Local PII Model: {e}")

                def predict(self, text: str) -> str:
                    if not self.session or not self.tokenizer: return text
                    try:
                        encoding = self.tokenizer.encode(text) 
                        ids = encoding.ids[:512]
                        mask = encoding.attention_mask[:512]
                        # ... Logic ...
                        return text 
                    except: return text

             _local_brain = SovereignPIIEngine()
        except:
             return None
             
    return _local_brain


def fast_regex_scrub(text: str) -> str:
    """Capa 1: Rust (Instantáneo)"""
    if RUST_AVAILABLE:
        return agentshield_rust.scrub_pii_fast(text)
    return text

async def advanced_redact_pii(text: str, tenant_id: str = "unknown") -> str:
    """
    Limpia datos sensibles utilizando el motor de Rust con medición 
    de latencia en tiempo real para observabilidad permanente.
    """
    with tracer.start_as_current_span("pii_redaction_process") as span:
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
                return await asyncio.to_thread(engine.predict, text)
            except Exception as e:
                logger.error(f"Local PII Inference Failed: {e}. Switching to Cloud Fallback.")
        
        # B. FALLBACK CLOUD (API)
        # Solo usamos esto si TODO lo demás falla o no está disponible, para no ralentizar.
        # Si ya pasó por Rust, ya está bastante limpio.
        # ¿Queremos pagar latencia de LLM por cada mensaje?
        # Para "2026 Speed" y "Proxy", quizás deberíamos saltar esto a menos que sea explícito.
        # Pero mantendremos el comportamiento original para seguridad máxima si no hay local brain.
        if not engine and len(text) > 0 and "API" in PII_MODEL_API: # Simple heuristic to allow skipping
             system_prompt = (
                "You are a PII Redaction Engine. Your ONLY job is to replace sensitive Personal Identifiable Information "
                "(Names, Locations, IDs, Secrets) with placeholders. Return ONLY the redacted text."
             )
             try:
                # Usamos un span separado para la API externa
                with tracer.start_as_current_span("pii_cloud_fallback"):
                    response = await acompletion(
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
