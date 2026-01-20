# agentshield_core/app/workers/trust_healer.py
import asyncio
import logging

from app.db import supabase
from app.services.trust_system import trust_system

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentshield.healer")


async def run_trust_healing_cycle():
    """
    Recuperación de Confianza (Fairness Engine).
    Regla: Si score < 100 Y no hay incidentes en 24h -> +5 Puntos.
    """
    logger.info("🏥 [HEALER] Iniciando ciclo de recuperación (Fairness Engine)...")

    try:
        # 1. Traer usuarios dañados (score < 100)
        damaged_users = (
            supabase.table("user_profiles")
            .select("user_id, tenant_id, trust_score")
            .lt("trust_score", 100)
            .execute()
        )

        count_healed = 0

        for user in damaged_users.data:
            # 2. Verificar "Clean Sheet" en las últimas 24h
            # Buscamos eventos negativos recientes
            recent_incidents = (
                supabase.table("trust_events")
                .select("id")
                .eq("user_id", user["user_id"])
                .lt("change_amount", 0)
                .gte("created_at", "now() - interval '24 hours'")
                .execute()
            )

            if not recent_incidents.data:
                # 3. ¡Amnistía! (+5 puntos diarios)
                await trust_system.adjust_score(
                    tenant_id=user["tenant_id"],
                    user_id=user["user_id"],
                    delta=5,
                    reason="Auto-Healing: 24h without incidents (Fairness Bonus)",
                    event_type="HEAL_DAILY",
                )
                count_healed += 1
                logger.info(
                    f"✨ [HEALER] Healed User {user['user_id']}: {user['trust_score']} -> +5pts"
                )

        logger.info(f"🏥 [HEALER] Cycle complete. Restored trust for {count_healed} employees.")

    except Exception as e:
        logger.error(f"🏥 [HEALER] Error crítico en el proceso de healing: {e}")


if __name__ == "__main__":
    asyncio.run(run_trust_healing_cycle())
