 # agentshield_core/app/estimator.py
 import asyncio
 import logging
 from typing import Any, Dict, Optional
 
 from litellm import model_cost
 
 from app.db import redis_client, supabase
 from app.utils import fast_json as json
 
 logger = logging.getLogger("agentshield.estimator")
 
 
 class MultimodalEstimator:
     """
     Estimador Financiero Universal Adaptativo.
     Aprende y se auto-calibra en tiempo real basándose en el uso real del sistema.
     """
 
     def __init__(self):
         # 1. FALLBACKS ACTUALIZADOS 2026 (Estado del Arte)
         # Estos ratios representan la media de tokens de SALIDA por cada token de ENTRADA.
         self.fallback_ratios = {
             # --- Tareas de Texto ---
             "TEXT_SUMMARIZATION": 0.35,  # Los modelos modernos son más eficientes resumiendo.
             "TEXT_EXTRACTION": 0.45,  # El formato JSON y Markdown añade mucho peso.
             "TEXT_TRANSLATION": 1.35,  # Las traducciones a idiomas romances (ES/FR/IT) suelen expandirse un 35%.
             "TEXT_ANALYSIS_CRITIQUE": 1.80,  # Análisis detallado de documentos.
             # --- Generación Proactiva ---
             "CREATIVE_WRITING": 4.50,  # Los modelos actuales generan mucha literatura si se les pide escribir.
             "CODE_GENERATION": 3.80,  # Incluye comentarios, lógica de tests y boilerplate.
             "CHAT_CONVERSATIONAL": 1.60,  # Por la cortesía y explicaciones adicionales.
             # --- Razonamiento Profundo (Nueva Categoría 2026) ---
             "DEEP_REASONING": 12.0,  # Para modelos tipo o1/o3 o DeepSeek-R1 (tokens de "pensamiento").
             "LOGIC_PUZZLE": 5.0,  # Resolución de problemas lógicos complejos.
             # --- Multimodal (Input: Texto/Imagen -> Output: Texto) ---
             "VISION_DESCRIPTION": 0.80,  # Descripción de imágenes basada en tokens visuales.
             "DOCUMENT_PARSING": 0.60,  # Extracción de texto de PDFs/Imágenes.
             # --- Default ---
             "DEFAULT": 1.25,
         }
 
     async def _resolve_price(self, model: str) -> tuple[float, float]:
         # (Tu lógica existente de _resolve_price se mantiene igual...)
         try:
             info = model_cost.get(model)
             if info:
                 return info.get("input_cost_per_token", 0), info.get("output_cost_per_token", 0)
         except Exception:
             # Silent fallback for internal litellm lookup is acceptable here as we have DB fallback
             pass
 
         cache_key = f"price:{model}"
         cached = await redis_client.get(cache_key)
         if cached:
             p_in, p_out = cached.split("|")
             return float(p_in), float(p_out)
 
         res = (
             supabase.table("model_prices")
             .select("price_in, price_out")
             .eq("model", model)
             .eq("is_active", True)
             .execute()
         )
         if res.data:
             data = res.data[0]
             p_in = float(data["price_in"])
             p_out = float(data["price_out"])
             await redis_client.setex(cache_key, 86400, f"{p_in}|{p_out}")
             return p_in, p_out
 
         return 0.0, 0.0
 
     async def _get_dynamic_ratio(self, task_type: str, model: str) -> float:
         """
         Obtiene el ratio de expansión 'REAL' aprendido por el sistema.
         Prioridad: Específico del Modelo > Genérico de la Tarea > Fallback Estático.
         """
         task_type = task_type.upper()
 
         # A. Intentar buscar ratio específico para este modelo (ej: gpt-4 vs claude-3)
         # Porque Claude puede ser más verboso que GPT.
         model_key = f"stats:ratio:{model}:{task_type}"
         ratio = await redis_client.get(model_key)
         if ratio:
             return float(ratio)
 
         # B. Intentar buscar ratio global de la tarea
         global_key = f"stats:ratio:GLOBAL:{task_type}"
         ratio = await redis_client.get(global_key)
         if ratio:
             return float(ratio)
 
         # C. Fallback estático
         return self.fallback_ratios.get(task_type, self.fallback_ratios["DEFAULT"])
 
     async def learn_from_reality(
         self, task_type: str, model: str, input_tokens: int, output_tokens: int
     ):
         """
         FEEDBACK LOOP: Inyecta la realidad en el sistema.
         Se llama DESPUÉS de cada ejecución exitosa.
         Usa EMA (Exponential Moving Average) para suavizar picos.
         """
         if input_tokens < 10 or output_tokens == 0:
             return  # Ignorar ruido
 
         task_type = task_type.upper()
         current_ratio = output_tokens / input_tokens
 
         # Claves de Redis
         keys = [f"stats:ratio:{model}:{task_type}", f"stats:ratio:GLOBAL:{task_type}"]
 
         # Factor de suavizado (Alpha).
         # 0.1 significa que la nueva transacción pesa un 10% en el promedio.
         # Esto permite que el sistema se adapte rápido pero sin oscilaciones locas.
         ALPHA = 0.1
 
         for key in keys:
             try:
                 old_val = await redis_client.get(key)
                 if old_val:
                     # Fórmula EMA: Nuevo = (Actual * alpha) + (Viejo * (1-alpha))
                     new_val = (current_ratio * ALPHA) + (float(old_val) * (1.0 - ALPHA))
                 else:
                     new_val = current_ratio
 
                 # Guardamos con TTL largo (1 mes) para mantener la inteligencia
                 await redis_client.setex(key, 2592000, new_val)
             except Exception as e:
                 logger.error(f"Error learning ratio: {e}")
 
     async def estimate_cost(
         self, model: str, task_type: str, input_unit_count: float, metadata: dict[str, Any] = None
     ) -> float:
         """
         Calcula coste usando PRECIOS y RATIOS VIVOS.
         """
         metadata = metadata or {}
         model = model.lower()
         task_type = task_type.upper() if task_type else "DEFAULT"
 
         # ... (Lógica de Imagen/Audio/TTS se mantiene igual, es determinista) ...
         if "IMG_GENERATION" in task_type or "DALL-E" in model:
             # --- CASO 1: GENERACIÓN DE IMÁGENES (Precio por Item) ---
             # Detectar si es HD
             quality = metadata.get("quality", "standard")
             # Construimos clave compuesta para buscar en DB (ej: 'dall-e-3-hd')
             # Si no existe, fallback a 'dall-e-3'
             price_key = f"{model}-{quality}".lower()
 
             # Usamos price_in como "cost per unit" (Input Unit = 1 Image)
             unit_price, _ = await self._resolve_price(price_key)
 
             if unit_price == 0:
                 # Fallback a búsqueda directa del modelo base si la key compuesta falla
                 unit_price, _ = await self._resolve_price(model)
 
             # Fallback de seguridad extrema si DB está vacía (evitar $0)
             if unit_price == 0:
                 unit_price = 0.080 if quality == "hd" else 0.040
 
             # input_unit_count aquí es número de imágenes
             num_images = max(1, int(input_unit_count))
             return unit_price * num_images
 
         # --- SOPORTE VISION (GPT-4o / Turbo) ---
         # Coste dinámico basado en DB (clave: 'vision-image-avg')
         vision_cost = 0.0
         image_count = metadata.get("image_count", 0)
         if image_count > 0:
             # Buscamos precio promedio por imagen en DB
             v_price, _ = await self._resolve_price("vision-image-avg")
             if v_price == 0:
                 v_price = 0.003825  # Fallback seguridad
 
             vision_cost = image_count * v_price
 
         # --- LÓGICA DE TEXTO ACTUALIZADA ---
         price_in, price_out = await self._resolve_price(model)
 
         # Precios de seguridad
         if price_in == 0:
             price_in = 0.00001
         if price_out == 0:
             price_out = 0.00003
 
         # >>> AQUÍ ESTÁ LA MAGIA: Usamos el ratio dinámico <<<
         ratio = await self._get_dynamic_ratio(task_type, model)
 
         est_output_tokens = int(input_unit_count * ratio)
         est_output_tokens = min(est_output_tokens, 16000)  # Hard Cap actualizado a modelos nuevos
 
         total_cost_usd = (
             (input_unit_count * price_in) + (est_output_tokens * price_out) + vision_cost
         )
 
         # Conversión de divisa
         try:
             rate = float(await redis_client.get("config:exchange_rate") or 0.92)
         except Exception as e:
             logger.warning(f"Failed to fetch exchange rate, using default: {e}")
             rate = 0.92
 
         return total_cost_usd * rate
 
 
 estimator = MultimodalEstimator()
