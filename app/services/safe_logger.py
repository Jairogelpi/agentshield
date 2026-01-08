import logging
from app.services.pii_guard import advanced_redact_pii

class PIIRedactionFilter(logging.Filter):
    """
    Intercepta cada log ANTES de que salga hacia Logtail/Consola.
    Si detecta emails, teléfonos o nombres, los censura.
    """
    def filter(self, record):
        # 1. Limpiar el mensaje principal
        if isinstance(record.msg, str):
            # Solo aplicamos NLP pesado a mensajes de error o advertencia para no matar la CPU
            # o si el mensaje es sospechosamente largo (posible prompt dump)
            if record.levelno >= logging.ERROR or len(record.msg) > 100:
                try:
                    record.msg = advanced_redact_pii(record.msg)
                except:
                    # Fail-safe: Si falla PII guard, mejor no loguear el contenido original
                    record.msg = "[LOG REDACTION FAILED - CONTENT HIDDEN FOR SAFETY]"
        
        # 2. Limpiar argumentos (si usas logger.error("Hola %s", variable))
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    try:
                        new_args.append(advanced_redact_pii(arg))
                    except:
                        new_args.append("<REDACTED_ARG>")
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
            
        return True
