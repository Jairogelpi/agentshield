# app/services/god_tier_budget_enforcer.py
"""
God Tier Budget Enforcement (2026).
Real-time enforcement of user quotas, prepaid wallets, and anomaly detection.
"""
import logging
from typing import Tuple

from app.database import get_supabase
from app.services.identity import VerifiedIdentity
from app.services.spend_anomaly_detector import spend_anomaly_detector

logger = logging.getLogger("agentshield.god_tier_budget")


class GodTierBudgetEnforcer:
    """
    Revolutionary budget enforcement with 3-layer protection:
    1. User-level quotas
    2. Prepaid wallet balance
    3. ML-powered anomaly detection
    """
    
    def __init__(self):
        self.supabase = get_supabase()
    
    async def check_all_limits(
        self,
        identity: VerifiedIdentity,
        estimated_cost: float
    ) -> Tuple[bool, str]:
        """
        God Tier enforcement: All checks in one.
        
        Returns:
            (allowed, reason)
        """
        # LAYER 1: User Quota Check
        allowed, reason = await self._check_user_quota(identity.user_id, estimated_cost)
        if not allowed:
            return False, f"User Quota: {reason}"
        
        # LAYER 2: Prepaid Wallet Check
        allowed, reason = await self._check_prepaid_wallet(identity.tenant_id, estimated_cost)
        if not allowed:
            return False, f"Wallet: {reason}"
        
        # LAYER 3: Anomaly Detection
        allowed, reason = await self._check_anomaly(identity.user_id, estimated_cost)
        if not allowed:
            return False, f"Anomaly: {reason}"
        
        return True, "OK"
    
    async def _check_user_quota(self, user_id: str, cost: float) -> Tuple[bool, str]:
        """Check if user has quota remaining."""
        try:
            result = self.supabase.table("user_quotas")\
                .select("*")\
                .eq("user_id", user_id)\
                .single()\
                .execute()
            
            if not result.data:
                # No quota configured = no limit
                return True, "OK"
            
            quota = result.data
            
            # Check daily limit
            if quota["current_daily_spend"] + cost > quota["daily_limit_usd"]:
                logger.warning(
                    f"🚫 User {user_id} daily quota exceeded: "
                    f"${quota['current_daily_spend']:.2f} + ${cost:.2f} > ${quota['daily_limit_usd']:.2f}"
                )
                return False, f"Daily limit ${quota['daily_limit_usd']:.2f} exceeded"
            
            # Check monthly limit
            if quota["current_monthly_spend"] + cost > quota["monthly_limit_usd"]:
                logger.warning(
                    f"🚫 User {user_id} monthly quota exceeded: "
                    f"${quota['current_monthly_spend']:.2f} + ${cost:.2f} > ${quota['monthly_limit_usd']:.2f}"
                )
                return False, f"Monthly limit ${quota['monthly_limit_usd']:.2f} exceeded"
            
            return True, "OK"
            
        except Exception as e:
            logger.error(f"Quota check failed: {e}")
            # Fail open for quota (don't block on errors)
            return True, "OK"
    
    async def _check_prepaid_wallet(self, tenant_id: str, cost: float) -> Tuple[bool, str]:
        """Check prepaid wallet balance."""
        try:
            result = self.supabase.table("wallets")\
                .select("*")\
                .eq("tenant_id", tenant_id)\
                .single()\
                .execute()
            
            if not result.data:
                return True, "OK"
            
            wallet = result.data
            
            # Only check if PREPAID
            if wallet["wallet_type"] != "PREPAID":
                return True, "OK"
            
            # Check balance
            if wallet["balance"] < cost:
                if not wallet["overdraft_protection"]:
                    logger.warning(
                        f"💳 Prepaid wallet depleted: "
                        f"balance=${wallet['balance']:.2f}, cost=${cost:.2f}"
                    )
                    return False, f"Insufficient funds (balance: ${wallet['balance']:.2f})"
                else:
                    logger.info(f"🛡️ Overdraft protection triggered for wallet {tenant_id}")
            
            # Check low balance threshold (alert only)
            if wallet["balance"] < wallet["low_balance_threshold"]:
                logger.warning(
                    f"⚠️ Low balance alert: "
                    f"${wallet['balance']:.2f} < ${wallet['low_balance_threshold']:.2f}"
                )
                # TODO: Send notification
            
            return True, "OK"
            
        except Exception as e:
            logger.error(f"Wallet check failed: {e}")
            # Fail closed for wallet (block on errors for safety)
            return False, "Wallet check error"
    
    async def _check_anomaly(self, user_id: str, cost: float) -> Tuple[bool, str]:
        """Check for spend anomalies using ML."""
        try:
            anomaly_score, severity, action = await spend_anomaly_detector.predict(
                user_id=user_id,
                current_spend=cost,
                time_window_hours=1
            )
            
            if action == "BLOCK":
                logger.error(
                    f"🚨 ANOMALY BLOCK: user={user_id}, "
                    f"score={anomaly_score:.2f}, severity={severity}"
                )
                return False, f"Anomalous spend detected (score: {anomaly_score:.2f})"
            
            elif action == "THROTTLE":
                logger.warning(
                    f"⚠️ ANOMALY THROTTLE: user={user_id}, "
                    f"score={anomaly_score:.2f}"
                )
                # TODO: Implement throttling logic (reduce rate limit)
                # For now, just log
            
            elif action == "ALERT":
                logger.info(
                    f"📢 ANOMALY ALERT: user={user_id}, "
                    f"score={anomaly_score:.2f}"
                )
                # TODO: Send notification
            
            return True, "OK"
            
        except Exception as e:
            logger.error(f"Anomaly check failed: {e}")
            # Fail open for anomaly (don't block on ML errors)
            return True, "OK"
    
    async def charge_user_quota(self, user_id: str, cost: float):
        """Deduct cost from user quota."""
        try:
            # Increment current spend
            self.supabase.table("user_quotas")\
                .update({
                    "current_daily_spend": f"current_daily_spend + {cost}",
                    "current_monthly_spend": f"current_monthly_spend + {cost}"
                })\
                .eq("user_id", user_id)\
                .execute()
            
        except Exception as e:
            logger.error(f"Failed to charge user quota: {e}")
    
    async def charge_prepaid_wallet(self, tenant_id: str, cost: float):
        """Deduct cost from prepaid wallet."""
        try:
            # Get wallet
            result = self.supabase.table("wallets")\
                .select("*")\
                .eq("tenant_id", tenant_id)\
                .single()\
                .execute()
            
            if not result.data or result.data["wallet_type"] != "PREPAID":
                return
            
            # Deduct balance
            new_balance = result.data["balance"] - cost
            
            self.supabase.table("wallets")\
                .update({"balance": new_balance})\
                .eq("tenant_id", tenant_id)\
                .execute()
            
            logger.info(f"💳 Prepaid wallet charged: ${cost:.2f} (new balance: ${new_balance:.2f})")
            
        except Exception as e:
            logger.error(f"Failed to charge prepaid wallet: {e}")


# Global instance
god_tier_budget_enforcer = GodTierBudgetEnforcer()
