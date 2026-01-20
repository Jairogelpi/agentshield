from app.db import supabase
import logging
from typing import Optional

logger = logging.getLogger("agentshield.trust")

class TrustSystem:
    async def adjust_score(self, tenant_id: str, user_id: str, amount: int, reason: str):
        """
        Ajusta el Trust Score de un usuario y registra el evento en el ledger.
        """
        try:
            # 1. Obtener score actual
            # Usamos single() para obtener un objeto, o manejamos el caso de que no exista perfil
            user_res = supabase.table("user_profiles").select("trust_score").eq("user_id", user_id).execute()
            
            current_score = 100
            if user_res.data:
                current_score = user_res.data[0].get('trust_score', 100) or 100
            else:
                # Si no existe perfil, lo creamos (Self-healing basic)
                # En un sistema real esto debería estar asegurado por triggers de auth
                pass 
            
            # 2. Calcular nuevo score (Clamp 0-100)
            new_score = max(0, min(100, current_score + amount))
            
            # 3. Determinar nuevo Tier de Riesgo
            new_tier = "LOW"
            if new_score < 50: new_tier = "HIGH"
            elif new_score < 80: new_tier = "MEDIUM"
            
            # 4. Actualizar Perfil
            # Upsert para manejar creación si no existe
            supabase.table("user_profiles").upsert({
                "user_id": user_id,
                "tenant_id": tenant_id, # Requerido si insertamos nuevo
                "trust_score": new_score,
                "risk_tier": new_tier
            }).execute()
            
            # 5. Registrar en el Ledger de Reputación
            supabase.table("reputation_ledger").insert({
                "tenant_id": tenant_id,
                "user_id": user_id,
                "change_amount": amount,
                "reason": reason,
                "new_score": new_score
            }).execute()
            
            logger.info(f"⚖️ Trust Score Updated for {user_id}: {current_score} -> {new_score} ({reason})")
            
        except Exception as e:
            logger.error(f"Failed to update Trust Score: {e}")

trust_system = TrustSystem()
