from litellm import model_cost
from typing import Dict, Any
from app.db import supabase, redis_client
from app.utils import fast_json as json

class MultimodalEstimator:
    """
    Estimador Financiero Universal para AgentShield.
    Soporta Texto, Visión, Audio y Generación de Imágenes.
    Actualizado para modelos 2024-2025.
    
    Zero-History: Usa heurísticas y precios oficiales de LiteLLM (o DB overrides).
    """
    
    def __init__(self):
        # TAXONOMÍA DE RATIOS DE EXPANSIÓN (Solo para Texto/Código)
        # Estos ratios son heurísticos y rara vez cambian (entropía del lenguaje).
        self.text_ratios = {
            "TEXT_SUMMARIZATION": 0.4,
            "TEXT_EXTRACTION": 0.1,
            "TEXT_TRANSLATION": 1.2, 
            "TEXT_FIXED_FORMAT": 1.0,
            "CODE_GENERATION": 2.5,
            "CREATIVE_WRITING": 15.0,
            "CHAT_CONVERSATIONAL": 1.5,
            "DEFAULT": 2.0
        }

    async def _resolve_price(self, model: str) -> (float, float):
        """
        Obtiene precio (in, out) de la fuente más fresca.
        Prioridad: Redis (Override) > LiteLLM (Oficial) > DB (Config Manual).
        """
        # 1. LiteLLM (Oficial y mantenido por comunidad)
        # Es lo más cercano a "Tiempo Real" sin calls HTTP extra.
        try:
             info = model_cost.get(model)
             if info:
                 return info.get("input_cost_per_token", 0), info.get("output_cost_per_token", 0)
        except:
            pass

        # 2. Redis / DB (Overrides manuales del usuario)
        # Si LiteLLM falla o queremos un override, miramos nuestra DB.
        cache_key = f"price:{model}"
        cached = await redis_client.get(cache_key)
        if cached:
             p_in, p_out = cached.split("|")
             return float(p_in), float(p_out)

        # 3. DB Lookup (Source of Truth for overrides)
        res = supabase.table("model_prices").select("price_in, price_out").eq("model", model).eq("is_active", True).execute()
        if res.data:
            data = res.data[0]
            p_in = float(data['price_in'])
            p_out = float(data['price_out'])
            await redis_client.setex(cache_key, 86400, f"{p_in}|{p_out}")
            return p_in, p_out
            
        return 0.0, 0.0

    async def estimate_cost(self, 
                      model: str, 
                      task_type: str, 
                      input_unit_count: float, 
                      metadata: Dict[str, Any] = None) -> float:
        """
        Calcula el coste estimado (PRE-FLIGHT).
        
        Args:
            model: Nombre del modelo (gpt-4o, dall-e-3, whisper-1)
            task_type: Categoría seleccionada en el Dashboard (TEXT_SUMMARIZATION, IMG_GENERATION...)
            input_unit_count: 
                - Para Texto: Cantidad de Tokens de entrada.
                - Para TTS: Cantidad de Caracteres.
                - Para Audio/Video: Minutos de duración.
                - Para Img Gen: Número de imágenes solicitadas.
            metadata: Datos extra (ej: resolución, calidad).
        """
        metadata = metadata or {}
        # Normalizar modelo y task_type
        model = model.lower()
        if not task_type: task_type = "DEFAULT"
        task_type = task_type.upper()

        # --- CASO 1: GENERACIÓN DE IMÁGENES (Precio por Item) ---
        if "IMG_GENERATION" in task_type or "DALL-E" in model:
            # Detectar si es HD
            quality = metadata.get("quality", "standard")
            price_key = f"{model}-{quality}" if quality == "hd" else model
            
            # Usamos price_in como "cost per unit"
            unit_price, _ = await self._resolve_price(price_key) 
            if unit_price == 0: 
                 # Fallback a búsqueda directa del modelo base si la key compuesta falla
                 unit_price, _ = await self._resolve_price(model)
            
            # input_unit_count aquí es número de imágenes
            num_images = max(1, int(input_unit_count)) 
            return unit_price * num_images

        # --- CASO 2: AUDIO TRANSCRIPTION (Precio por Minuto) ---
        if "AUDIO_TRANSCRIPTION" in task_type or "WHISPER" in model:
            price_per_min, _ = await self._resolve_price("whisper-1") # Normalizamos key
            if price_per_min == 0: price_per_min, _ = await self._resolve_price(model)
            
            minutes = float(input_unit_count)
            return price_per_min * minutes

        # --- CASO 3: TEXT TO SPEECH (Precio por Caracter) ---
        if "AUDIO_SPEECH" in task_type or "TTS" in model:
            price_per_char, _ = await self._resolve_price("tts-1")
            
            chars = int(input_unit_count)
            return price_per_char * chars

        # --- CASO 4: TEXTO / VISIÓN ANALYSIS (Precio por Token) ---
        # Aquí usamos los Ratios de expansión
        price_in, price_out = await self._resolve_price(model)
        
        # Si todo falla, usar precios de seguridad (Worst Case GPT-4 level)
        if price_in == 0: price_in = 0.00001
        if price_out == 0: price_out = 0.00003

        # Calcular Tokens de Salida Estimados usando Ratios
        ratio = self.text_ratios.get(task_type, self.text_ratios["DEFAULT"])
        
        # Lógica especial para Visión (Análisis de Imagen)
        if task_type == "IMG_ANALYSIS":
            # Asumimos que input_unit_count ya incluye los tokens de la imagen
            ratio = 0.2 
            
        est_output_tokens = int(input_unit_count * ratio)
        
        # Hard Cap (Límite Técnico del Modelo)
        est_output_tokens = min(est_output_tokens, 4000) 

        total_cost_usd = (input_unit_count * price_in) + (est_output_tokens * price_out)
        
        # 5. CONVERSIÓN DE DIVISA (FOREX REAL)
        # Obtenemos el tipo de cambio del Oráculo
        try:
            rules_json = await redis_client.get("system_config:arbitrage_rules")
            rules = json.loads(rules_json) if rules_json else {}
            rate = float(rules.get("exchange_rate", 0.92))
        except:
            rate = 0.92 # Fallback seguro
            
        return total_cost_usd * rate

    async def calculate_projected_loss(self, original_model: str, used_model: str, tokens: int) -> float:
        """
        Calcula la diferencia de precio TOTAL entre el modelo original y el usado (o el que se pudo usar).
        """
        _, p_out_orig = await self._resolve_price(original_model)
        _, p_out_used = await self._resolve_price(used_model)
        
        # Asumimos que el input cost también varía, pero para simplificar métrica FOMO usamos output o promedio
        # O mejor: sumamos input y output savings si tuvieramos el split
        # Aquí usamos p_out como proxy del "coste por token" general para la métrica rápida
        
        diff = p_out_orig - p_out_used
        total_loss = diff * tokens
        return max(0.0, total_loss)

estimator = MultimodalEstimator()
