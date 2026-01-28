import logging

logger = logging.getLogger("agentshield.tokenizer")

try:
    import tiktoken

    _ENCODINGS = {}

    def get_token_count(text: str, model: str = "gpt-4") -> int:
        """
        Calcula el número real de tokens usando tiktoken.
        """
        if not text:
            return 0
        try:
            # Intentamos obtener el encoding para el modelo específico
            if model not in _ENCODINGS:
                try:
                    _ENCODINGS[model] = tiktoken.encoding_for_model(model)
                except:
                    # Fallback a cl100k_base (usado por GPT-4 y otros modernos)
                    _ENCODINGS[model] = tiktoken.get_encoding("cl100k_base")

            return len(_ENCODINGS[model].encode(text))
        except Exception as e:
            logger.warning(f"Tiktoken failed: {e}")
            return len(text) // 4  # Fallback heurístico 100% seguro

except ImportError:
    logger.warning("Tiktoken not installed. Using heuristic fallback (length / 4).")

    def get_token_count(text: str, model: str = "gpt-4") -> int:
        if not text:
            return 0
        return len(text) // 4
