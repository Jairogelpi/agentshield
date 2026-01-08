# agentshield_core/app/services/pii_guard.py
import re
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
import logging

logger = logging.getLogger("agentshield.pii_guard")

# --- CAPA 1: MOTOR REGEX (Simulación de Edge - <1ms) ---
# Compilamos patrones al inicio para velocidad máxima.
# Esto filtra lo obvio instantáneamente sin gastar CPU en IA.
REGEX_PATTERNS = {
    "EMAIL": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "PHONE_INT": re.compile(r'\+(9[976]\d|8[987530]\d|6[987]\d|5[90]\d|42\d|3[875]\d|2[98654321]\d|9[8543210]|8[6421]|6[6543210]|5[87654321]|4[987654310]|3[9643210]|2[70]|7|1)\d{1,14}'),
    "IP_ADDRESS": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    "CREDIT_CARD": re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b')
}

def fast_regex_scrub(text: str) -> str:
    """
    Limpieza determinista de alta velocidad.
    Elimina datos estructurados antes de pasar al modelo pesado.
    """
    for label, pattern in REGEX_PATTERNS.items():
        text = pattern.sub(f"<{label}>", text)
    return text

# --- CAPA 2: MOTOR IA (Presidio/Spacy - ~100ms) ---
# Inicialización Lazy de Motores (Singleton)
analyzer = None
anonymizer = None

def get_engines():
    global analyzer, anonymizer
    if not analyzer:
        analyzer = AnalyzerEngine()
        anonymizer = AnonymizerEngine()
    return analyzer, anonymizer

def advanced_redact_pii(text: str) -> str:
    """
    Híbrido de PII: Regex (Capa Rápida) + NLP (Capa Profunda).
    Estrategia Fail-Closed: Si falla, bloquea.
    """
    try:
        # PASO 1: FAST PATH (Regex) - Velocidad de 'Edge'
        # Limpiamos emails, teléfonos y tarjetas instantáneamente.
        clean_text = fast_regex_scrub(text)
        
        # PASO 2: DEEP PATH (NLP) - Contexto y Nombres
        # Solo usamos la IA para lo que el Regex no puede entender (Nombres, Ubicaciones).
        analyzer_engine, anonymizer_engine = get_engines()
        
        results = analyzer_engine.analyze(
            text=clean_text, 
            language='es', 
            # Quitamos EMAIL_ADDRESS y PHONE_NUMBER de aquí porque ya lo hizo el regex mejor y más rápido
            entities=["PERSON", "LOCATION", "US_SSN", "IBAN_CODE"] 
        )
        
        anonymized_result = anonymizer_engine.anonymize(
            text=clean_text,
            analyzer_results=results,
            operators={
                "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED_PII>"}),
                "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
                "LOCATION": OperatorConfig("replace", {"new_value": "<LOCATION>"}),
            }
        )
        return anonymized_result.text

    except Exception as e:
        logger.critical(f"⚠️ PII Guard Security Failure: {e}")
        # Política Fail-Closed (Bloqueo si falla la seguridad)
        raise ValueError("Security Subsystem Failed: PII Guard could not load. Request blocked.")
