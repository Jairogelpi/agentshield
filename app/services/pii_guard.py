from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Inicialización Lazy de Motores (Singleton)
analyzer = None
anonymizer = None

def get_engines():
    global analyzer, anonymizer
    if not analyzer:
        # Cargar NLP engine solo cuando se necesite
        analyzer = AnalyzerEngine()
        anonymizer = AnonymizerEngine()
    return analyzer, anonymizer

def advanced_redact_pii(text: str) -> str:
    """
    Sanitización profunda usando NLP (Spacy + Presidio).
    Detecta entidades complejas en español que el regex ignora.
    """
    try:
        analyzer, anonymizer = get_engines()
        
        # 1. Análisis
        # Detecta: Nombres, Ubicaciones, Teléfonos, Emails, Tarjetas, IBANs
        results = analyzer.analyze(
            text=text, 
            language='es', 
            entities=["PERSON", "LOCATION", "PHONE_NUMBER", "EMAIL_ADDRESS", "CREDIT_CARD", "IBAN_CODE", "US_SSN"]
        )
        
        # 2. Anonimización
        # Reemplazamos por etiquetas tipo <PERSON>, <LOCATION>
        anonymized_result = anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators={
                "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED_PII>"}),
                "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
                "LOCATION": OperatorConfig("replace", {"new_value": "<LOCATION>"}),
                "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE>"})
            }
        )
        return anonymized_result.text
    except Exception as e:
        print(f"⚠️ PII Guard Error: {e}")
        # Fail-Closed: Mejor bloquear que filtrar datos
        raise ValueError("PII Protection System failed. Blocking request for safety.")
