import logging
import re
from typing import Tuple

logger = logging.getLogger("agentshield.safety")


class SafetyEngine:
    def __init__(self):
        # Patrones comunes de Jailbreak / Prompt Injection que pueden aparecer en flujos
        self.jailbreak_patterns = [
            r"(?i)system\s*override",
            r"(?i)ignore\s*previous\s*instructions",
            r"(?i)you\s*are\s*now\s*unfiltered",
            r"(?i)dan\s*mode",
            r"(?i)jailbreak",
        ]

        # Patrones de PII de salida: Datos que la IA NUNCA debe decir (Secrets)
        self.outbound_secret_patterns = [
            r"AS-KEY-[A-Z0-9]{12}",  # Ejemplo de API Key interna
            r"CONFIDENTIAL-PROJECT-[A-Z]+",
            r"\b[A-Z0-9._%+-]+@company-internal\.com\b",  # Emails internos
        ]

    def scan_chunk(self, text: str) -> Tuple[bool, str, str]:
        """
        Escanea un chunk de texto.
        Retorna (is_threat, reason, cleaned_text)
        """
        # 1. Jailbreak Detection (Heurística rápida)
        for pattern in self.jailbreak_patterns:
            if re.search(pattern, text):
                logger.warning(f"🚨 Jailbreak Attempt Detected in stream: {pattern}")
                return True, "JAILBREAK_DETECTED", text

        # 2. Outbound PII (Redacción en vivo)
        cleaned_text = text
        detected_leak = False
        for pattern in self.outbound_secret_patterns:
            if re.search(pattern, cleaned_text):
                cleaned_text = re.sub(pattern, "[SECRET_REDACTED]", cleaned_text)
                detected_leak = True

        if detected_leak:
            logger.info("🛡️ Outbound Secret Redacted in stream.")
            return False, "PII_REDACTED", cleaned_text

        return False, "SAFE", cleaned_text


safety_engine = SafetyEngine()
