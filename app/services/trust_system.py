import logging
from typing import Any, Dict

from app.db import redis_client, supabase
from app.services.event_bus import event_bus

logger = logging.getLogger("agentshield.trust")

# Configuración de Umbrales (Business Logic)
TRUST_CONFIG = {
    "default": 100,
    "min": 0,
    "max": 100,
    "thresholds": {
        "downgrade": 70,  # < 70: Pierde acceso a modelos top (Ferrari -> Toyota)
        "supervision": 30,  # < 30: Bloqueo crítico / requiere aprobación humana
    },
}


class TrustSystem:
    def _key(self, tenant_id: str, user_id: str) -> str:
        return f"trust:{tenant_id}:{user_id}"

    async def get_score(self, tenant_id: str, user_id: str) -> int:
        """Lectura ultra-rápida desde Redis (Latencia < 2ms)"""
        key = self._key(tenant_id, user_id)
        raw = await redis_client.get(key)

        if raw is None:
            # Inicialización Lazy Atómica (SETNX)
            await redis_client.setnx(key, TRUST_CONFIG["default"])
            return TRUST_CONFIG["default"]

        try:
            return int(raw)
        except ValueError:
            # Self-healing si hay corrupción de datos
            await redis_client.set(key, TRUST_CONFIG["default"])
            return TRUST_CONFIG["default"]

    async def enforce_policy(
        self, tenant_id: str, user_id: str, requested_model: str
    ) -> dict[str, Any]:
        """
        El "Decision Gate" del Decision Graph.
        Determina si degradamos el modelo o bloqueamos por seguridad.
        """
        score = await self.get_score(tenant_id, user_id)

        policy = {
            "trust_score": score,
            "mode": "normal",
            "effective_model": requested_model,
            "requires_approval": False,
            "blocking_reason": None,
        }

        # 1. ZONA DE SUPERVISIÓN CRÍTICA (< 30)
        if score < TRUST_CONFIG["thresholds"]["supervision"]:
            policy.update(
                {
                    "mode": "supervised",
                    "effective_model": "agentshield-secure",  # Forzar modelo ultra-filtrado
                    "requires_approval": True,
                    "blocking_reason": "Trust Score critical (<30). Access restricted.",
                }
            )
            return policy

        # 2. ZONA RESTRINGIDA (30 - 69): Downgrade de Modelos
        if score < TRUST_CONFIG["thresholds"]["downgrade"]:
            # Identificamos si el modelo es "Premium"
            is_premium = any(
                x in requested_model.lower() for x in ["gpt-4", "opus", "sonnet", "smart", "o1"]
            )

            if is_premium:
                policy.update(
                    {
                        "mode": "restricted",
                        "effective_model": "agentshield-fast",  # Downgrade automático a modelo barato
                        "blocking_reason": "Premium model restricted due to trust score (behavioral tiering).",
                    }
                )
            else:
                policy["mode"] = "restricted"
        
        # 3. SMART ARBITRAGE (Profit Center Logic)
        # Si el usuario NO pide explícitamente "raw capability" y la tarea es simple, ahorramos dinero.
        # Esto valida la promesa de "-60% Costes".
        if "gpt-4" in requested_model.lower() or "opus" in requested_model.lower():
             # NOTA: En producción, esto usaría el Clasificador de Intención (router).
             # Por ahora, simulamos que si no es un usuario VIP (Trust > 95), aplicamos ahorro agresivo.
             if score < 95:
                 logger.info(f"💰 Arbitage Opportunity: Downgrading {requested_model} to agentshield-fast for optimization.")
                 policy["effective_model"] = "agentshield-fast"
                 policy["arbitrage_active"] = True

        return policy

    async def adjust_score(
        self,
        tenant_id: str,
        user_id: str,
        delta: int,
        reason: str,
        event_type: str,
        trace_id: str = None,
        metadata: dict = None,
    ):
        """
        Escritura Atómica en Redis + Persistencia Asíncrona en Postgres.
        Se ejecuta in background para no penalizar la latencia del chat.
        """
        key = self._key(tenant_id, user_id)

        # 1. Pipeline Redis (Atómico)
        pipe = redis_client.pipeline()
        pipe.setnx(key, TRUST_CONFIG["default"])
        pipe.incrby(key, delta)
        results = await pipe.execute()

        raw_new_score = int(results[-1])

        # 2. Clamping (0 - 100)
        final_score = max(TRUST_CONFIG["min"], min(TRUST_CONFIG["max"], raw_new_score))

        # Si el clamping actuó, corregimos Redis
        if final_score != raw_new_score:
            await redis_client.set(key, final_score)

        logger.info(
            f"⚖️ TRUST ADJUSTMENT: User {user_id} | Δ {delta} | Result {final_score} | {reason}"
        )

        # 3. Persistencia en DB (Black Box Logger)
        try:
            # Reportamos el evento
            supabase.table("trust_events").insert(
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "change_amount": delta,
                    "new_score": final_score,
                    "reason": reason,
                    "trace_id": trace_id,
                    "metadata": metadata or {},
                }
            ).execute()

            # Actualizamos perfil para el Dashboard (Consistencia Eventual)
            current_tier = "LOW"
            if final_score < 30:
                current_tier = "HIGH"
            elif final_score < 70:
                current_tier = "MEDIUM"

            supabase.table("user_profiles").update(
                {"trust_score": final_score, "risk_tier": current_tier}
            ).eq("user_id", user_id).execute()

        except Exception as e:
            logger.error(f"Failed to persist trust event to DB: {e}")

        # 4. Sistema Inmunológico (Event Bus)
        if delta < 0:
            severity = "CRITICAL" if final_score < 30 else "WARNING"
            import asyncio

            asyncio.create_task(
                event_bus.publish(
                    tenant_id=tenant_id,
                    event_type="TRUST_SCORE_DROP",
                    severity=severity,
                    details={
                        "old_score": results[-1] - delta,  # Aproximación rápida
                        "new_score": final_score,
                        "delta": delta,
                        "reason": reason,
                    },
                    actor_id=user_id,
                    trace_id=trace_id,
                )
            )


trust_system = TrustSystem()
