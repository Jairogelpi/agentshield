# agentshield_core/app/services/market_oracle.py
import httpx
import numpy as np
import logging
import asyncio
from app.utils import fast_json as json
from app.db import supabase, redis_client

logger = logging.getLogger("agentshield.oracle")

import os

MARKET_URL = os.getenv("ORACLE_MARKET_URL", "https://openrouter.ai/api/v1/models")
FOREX_URL = os.getenv("ORACLE_FOREX_URL", "https://api.frankfurter.app/latest?from=USD&to=EUR")

# Tuning Parameters (Calibración)
WEIGHT_SLOW = float(os.getenv("ORACLE_WEIGHT_SLOW", "0.7"))
WEIGHT_FAST = float(os.getenv("ORACLE_WEIGHT_FAST", "0.3"))
VOLATILITY_BUFFER = float(os.getenv("ORACLE_VOLATILITY_BUFFER", "1.05"))

async def get_real_exchange_rate() -> float:
    """Obtiene el tipo de cambio USD -> EUR en tiempo real"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(FOREX_URL, timeout=5)
            data = resp.json()
            rate = data.get("rates", {}).get("EUR", 0.92) # Default conservador
            logger.info(f"💱 Forex Rate: 1 USD = {rate} EUR")
            return float(rate)
    except Exception as e:
        logger.warning(f"⚠️ Forex API Failed, using fallback: {e}")
        return 0.92 # Valor seguro histórico

async def get_smart_efficiency_factor() -> float:
    """
    Cálculo de Eficiencia con 'Momentum'.
    Aplica lógica conservadora: Reacciona rápido a las pérdidas, lento a las ganancias.
    """
    try:
        def _fetch_stats():
            return supabase.rpc("get_dual_window_stats").execute()
            
        res = await asyncio.to_thread(_fetch_stats)
        if not res.data: return 0.0
        
        data = res.data[0]
        
        # 1. Calcular Ratios Puros
        t1h = data.get('total_1h', 0)
        ratio_fast = (data.get('hits_1h', 0) / t1h) if t1h > 10 else 0.0 # Mínimo 10 reqs para fiabilidad
        
        t24h = data.get('total_24h', 0)
        ratio_slow = (data.get('hits_24h', 0) / t24h) if t24h > 0 else 0.0
        
        # 2. INTELIGENCIA FINANCIERA (La Joya)
        # Decision Matrix:
        
        if ratio_fast < ratio_slow:
            # CASO: La eficiencia se está desplomando (Panic Mode)
            # Acción: Usar el ratio rápido inmediatamente para subir precios.
            # Razón: No queremos vender barato si nuestros costes reales acaban de subir.
            final_factor = ratio_fast
            trend = "📉 CRASHING (Using Fast Window)"
        
        else:
            # CASO: La eficiencia está subiendo (Greed Mode)
            # Acción: Usar un promedio ponderado (70% lento / 30% rápido).
            # Razón: No bajamos precios de inmediato. Retenemos el beneficio extra
            # por si esto es solo un pico temporal de suerte.
            final_factor = (ratio_slow * WEIGHT_SLOW) + (ratio_fast * WEIGHT_FAST)
            trend = "📈 IMPROVING (Profit Taking Mode)"

        logger.info(f"🧠 Smart Efficiency Audit:")
        logger.info(f"   - Now (1h): {ratio_fast*100:.1f}% | Normal (24h): {ratio_slow*100:.1f}%")
        logger.info(f"   - Trend: {trend}")
        logger.info(f"   - Applied Discount: {final_factor*100:.1f}%")
        
        return float(final_factor)

    except Exception as e:
        logger.error(f"Smart efficiency calc failed: {e}")
        return 0.0

async def update_market_rules():
    logger.info("🔮 Oráculo V3: Iniciando Análisis de Mercado + Momentum...")
    
    try:
        async with httpx.AsyncClient() as client:
            # Paralelismo máximo
            market_task = client.get(MARKET_URL, timeout=10)
            forex_task = get_real_exchange_rate()
            efficiency_task = get_smart_efficiency_factor() # <--- LA NUEVA INTELIGENCIA
            
            market_resp = await market_task
            eur_rate = await forex_task
            smart_discount = await efficiency_task 
            
            market_resp.raise_for_status()
            data = market_resp.json().get("data", [])

        effective_prices = []
        
        for m in data:
            try:
                pricing = m.get("pricing", {})
                p_in = float(pricing.get("prompt", 0))
                p_out = float(pricing.get("completion", 0))
                
                if p_in <= 0 or p_out <= 0: continue
                if p_in * 1_000_000 > 100: continue # Ignorar outliers absurdos

                # --- APLICACIÓN DEL DESCUENTO INTELIGENTE ---
                # Usamos el 'smart_discount' que ya calculó el peor/mejor caso
                effective_p_in = p_in * (1.0 - smart_discount)
                
                # --- FACTOR DE SEGURIDAD DE VOLATILIDAD (NUEVO) ---
                # Si el mercado es volátil, añadimos un pequeño buffer del 5% al coste
                # para cubrir fluctuaciones de divisa intradía.
                volatility_buffer = VOLATILITY_BUFFER 
                
                total_cost_usd = ((1_000_000 * effective_p_in) + (300_000 * p_out)) * volatility_buffer
                
                # Conversión a EUR
                effective_prices.append(total_cost_usd * eur_rate)
                
            except: continue

        if not effective_prices:
            return

        # 3. CÁLCULO ESTADÍSTICO (Numpy)
        arr = np.array(effective_prices)
        
        # Percentiles dinámicos
        p20_cheap = float(np.percentile(arr, 20)) # Lo que cuesta un modelo "Barato" hoy en EUR
        p50_median = float(np.median(arr))
        p80_premium = float(np.percentile(arr, 80)) # Lo que cuesta un GPT-4 class hoy en EUR

        logger.info(f"📊 Calibración Final:")
        logger.info(f"   - Factor de Descuento (Tu Eficiencia): {smart_discount*100:.1f}%")
        logger.info(f"   - Tasa de Cambio: 1 USD = {eur_rate:.4f} EUR")
        logger.info(f"   - Coste 'Barato' (P20): {p20_cheap:.4f} € / ciclo")
        logger.info(f"   - Coste 'Premium' (P80): {p80_premium:.4f} € / ciclo")

        # 4. GENERAR REGLAS DE NEGOCIO
        # Convertimos de nuevo a precio unitario base para las reglas
        # (Aprox dividimos por el volumen usado en el cálculo 1.3M)
        unit_cheap = p20_cheap / 1_300_000
        unit_premium = p80_premium / 1_300_000

        new_rules = {
            "currency": "EUR",
            "exchange_rate": eur_rate,
            "thresholds": {
                "trivial_score": 30,
                "standard_score": 75 # Subimos exigencia si el mercado está barato
            },
            "pricing": {
                # Precios normalizados por 1 Token (aprox) para comparación rápida
                "trivial_max_price": unit_cheap * 1_000_000, 
                "standard_min_price": (unit_cheap * 1_000_000) * 0.8,
                "standard_max_price": unit_premium * 1_000_000
            },
            "latency_sla": 2000,
            "last_calibration": "now()"
        }

        # 5. ACTUALIZACIÓN ATÓMICA
        # Guardamos también los precios individuales para el Estimador Dinámico
        model_prices = {}
        for m in data:
            mid = m.get("id")
            pricing = m.get("pricing", {})
            p_in = float(pricing.get("prompt", 0))
            p_out = float(pricing.get("completion", 0))
            if mid and p_in > 0 and p_out > 0:
                model_prices[mid] = {"input": p_in * 1_000_000, "output": p_out * 1_000_000}

        def _save_rules():
            # Guardamos reglas generales
            supabase.table("system_config").upsert({
                "key": "arbitrage_rules",
                "value": new_rules,
                "updated_at": "now()"
            }).execute()
            # Guardamos caché de modelos
            supabase.table("system_config").upsert({
                "key": "market_prices",
                "value": model_prices,
                "updated_at": "now()"
            }).execute()

        await asyncio.to_thread(_save_rules)

        # Invalidad caché distribuida
        await redis_client.delete("system_config:arbitrage_rules")
        await redis_client.set("system_config:market_prices", json.dumps(model_prices), ex=3600)
        
        logger.info(f"✅ Reglas Financieras Recalibradas. {len(model_prices)} modelos indexados para cobro dinámico.")
        return new_rules

    except Exception as e:
        logger.error(f"❌ Oracle V3 Failure: {e}")
