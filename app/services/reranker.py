# app/services/reranker.py
from litellm import acompletion
import asyncio
import os
from rapidfuzz import fuzz

async def verify_cache_logic(new_prompt: str, cached_prompt: str) -> bool:
    Validación en dos capas:
    1. Léxica (Local - <1ms): Si es casi idéntico, aceptamos.
    2. Semántica (IA - <200ms): Si hay duda, preguntamos al modelo.
    """
    try:
        # CAPA 1: Validación léxica local con RapidFuzz
        # ratio 95 significa que las frases son prácticamente iguales (typos, espacios)
        lexical_score = fuzz.ratio(new_prompt.lower(), cached_prompt.lower())
        
        if lexical_score >= 90:
            return True # Aprobado instantáneamente sin red

        # CAPA 2: Validación con IA (solo para casos ambiguos)
        prompt_verificador = f"""
        Instrucción: Compara si estas dos preguntas piden exactamente la misma información.
        Pregunta A: "{new_prompt}"
        Pregunta B: "{cached_prompt}"
        ¿Es válido responder A usando la respuesta de B? Responde solo 'YES' o 'NO'.
        """
        
        # Implementamos timeout de 200ms para evitar latencia externa
        response = await asyncio.wait_for(
            acompletion(
                model="groq/llama-3.2-1b-preview", 
                messages=[{"role": "user", "content": prompt_verificador}],
                max_tokens=5, # Solo necesitamos YES/NO
                temperature=0
            ),
            timeout=0.2 # 200ms
        )
        
        verdict = response.choices[0].message.content.strip().upper()
        return "YES" in verdict
        
    except (asyncio.TimeoutError, Exception) as e:
        # Fallback silencioso: si hay timeout o error, devolvemos False
        # Mejor gastar tokens en el LLM real que dar una respuesta incorrecta.
        if isinstance(e, asyncio.TimeoutError):
            print(f"⚠️ Reranker skipped (Timeout > 200ms)")
        else:
            print(f"⚠️ Reranker Error: {e}")
        return False
