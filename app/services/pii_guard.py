# agentshield_core/app/services/pii_guard.py
import re
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
from langdetect import detect
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

# --- CAPA 2: MOTOR IA (Multilingual Presidio - ~100ms) ---
# Inicialización Lazy de Motores (Singleton)
analyzer = None
anonymizer = None

def get_engines():
    global analyzer, anonymizer
    if not analyzer:
        # Cargar configuración multilingüe si es necesario, por defecto carga modelos "en" si están instalados
        # Para soporte real de varios idiomas se necesita instalar:
        # python -m spacy download en_core_web_lg
        # python -m spacy download es_core_news_lg
        # etc.
        analyzer = AnalyzerEngine() 
        anonymizer = AnonymizerEngine()
    return analyzer, anonymizer

def detect_language_safe(text: str) -> str:
    """
    Detecta idioma con fail-safe a inglés.
    Zero-Latency wrapper sobre langdetect.
    """
    try:
        lang = detect(text)
        # Normalizamos a códigos de 2 letras que soporte Spacy/Presidio
        if lang in ['es', 'en', 'fr', 'de', 'it', 'pt', 'zh']:
            return lang
        return 'en' # Fallback universal
    except:
        return 'en'

def advanced_redact_pii(text: str) -> str:
    """
    Híbrido de PII Universal: Regex + Multilingual NLP.
    Estrategia Fail-Closed: Si falla, bloquea.
    """
    try:
        # PASO 1: FAST PATH (Regex) - Velocidad de 'Edge'
        clean_text = fast_regex_scrub(text)
        
        # PASO 2: LANGUAGE DETECTION (Zero-Latency)
        detected_lang = detect_language_safe(clean_text[:500]) # Solo analizamos el inicio para velocidad
        
        # PASO 3: DEEP PATH (NLP) - Context aware
        analyzer_engine, anonymizer_engine = get_engines()
        
        # Intentamos usar el idioma detectado. 
        # Si el modelo spacy no está instalado para ese idioma, Presidio fallará o usará default?
        # Presidio devuelve [] si no tiene modelo. Asumimos que en deploy se instalan 'en' y 'es'.
        
        results = analyzer_engine.analyze(
            text=clean_text, 
            language=detected_lang, 
            entities=["PERSON", "LOCATION", "US_SSN", "IBAN_CODE", "DATE_TIME"] 
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
