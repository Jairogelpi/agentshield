# app/routers/budget_management.py
"""
God Tier Budget Management API.
User quotas, prepaid wallets, and anomaly management.
"""
import logging
from typing import List, Optional
from uuid import UUID
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import get_supabase
from app.services.spend_anomaly_detector import spend_anomaly_detector

logger = logging.getLogger("agentshield.budget_api")

router = APIRouter(prefix="/budget", tags=["Budget Management"])


# Pydantic Models
class UserQuota(BaseModel):
    user_id: UUID
    tenant_id: UUID
    daily_limit_usd: float = Field(ge=0)
    monthly_limit_usd: float = Field(ge=0)
    current_daily_spend: float
    current_monthly_spend: float
    last_reset_daily: str
    last_reset_monthly: str


class UpdateQuotaRequest(BaseModel):
    daily_limit_usd: Optional[float] = Field(None, ge=0)
    monthly_limit_usd: Optional[float] = Field(None, ge=0)


class WalletInfo(BaseModel):
    id: UUID
    tenant_id: UUID
    balance: float
    wallet_type: str  # POSTPAID, PREPAID
    overdraft_protection: bool
    low_balance_threshold: float


class TopUpRequest(BaseModel):
    amount: float = Field(gt=0, le=10000)
    payment_method: str = Field(default="STRIPE")


class TopUpResponse(BaseModel):
    id: UUID
    wallet_id: UUID
    amount: float
    payment_method: str
    status: str
    created_at: str


class AnomalyResponse(BaseModel):
    id: UUID
    user_id: UUID
    detected_at: str
    anomaly_score: float
    spend_baseline: float
    spend_actual: float
    severity: str
    action_taken: str
    resolved: bool


# ============================================================================
# User Quotas
# ============================================================================

@router.get("/quotas/{user_id}", response_model=UserQuota)
async def get_user_quota(user_id: UUID, supabase=Depends(get_supabase)):
    """Get user's quota limits and current spend."""
    try:
        result = supabase.table("user_quotas")\
            .select("*")\
            .eq("user_id", str(user_id))\
            .single()\
            .execute()
        
        return UserQuota(**result.data)
        
    except Exception as e:
        raise HTTPException(status_code=404, detail="User quota not found")


@router.put("/quotas/{user_id}", response_model=UserQuota)
async def update_user_quota(
    user_id: UUID,
    request: UpdateQuotaRequest,
    supabase=Depends(get_supabase)
):
    """Update user's quota limits."""
    try:
        update_data = {}
        if request.daily_limit_usd is not None:
            update_data["daily_limit_usd"] = request.daily_limit_usd
        if request.monthly_limit_usd is not None:
            update_data["monthly_limit_usd"] = request.monthly_limit_usd
        
        result = supabase.table("user_quotas")\
            .update(update_data)\
            .eq("user_id", str(user_id))\
            .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="User quota not found")
        
        logger.info(f"✅ Updated quota for user {user_id}: {update_data}")
        
        return UserQuota(**result.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update quota: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quotas/{user_id}/reset-daily")
async def reset_daily_quota(user_id: UUID, supabase=Depends(get_supabase)):
    """Manually reset user's daily quota."""
    try:
        result = supabase.table("user_quotas")\
            .update({
                "current_daily_spend": 0,
                "last_reset_daily": "NOW()"
            })\
            .eq("user_id", str(user_id))\
            .execute()
        
        logger.info(f"✅ Reset daily quota for user {user_id}")
        
        return {"message": "Daily quota reset successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Wallets & Top-ups
# ============================================================================

@router.get("/wallets/{wallet_id}", response_model=WalletInfo)
async def get_wallet(wallet_id: UUID, supabase=Depends(get_supabase)):
    """Get wallet information."""
    try:
        result = supabase.table("wallets")\
            .select("*")\
            .eq("id", str(wallet_id))\
            .single()\
            .execute()
        
        return WalletInfo(**result.data)
        
    except Exception as e:
        raise HTTPException(status_code=404, detail="Wallet not found")


@router.post("/wallets/{wallet_id}/top-up", response_model=TopUpResponse)
async def create_top_up(
    wallet_id: UUID,
    request: TopUpRequest,
    supabase=Depends(get_supabase)
):
    """
    Create a top-up for a prepaid wallet.
    In production, this would integrate with Stripe/PayPal.
    """
    try:
        # Verify wallet exists and is PREPAID
        wallet = supabase.table("wallets")\
            .select("*")\
            .eq("id", str(wallet_id))\
            .single()\
            .execute()
        
        if wallet.data["wallet_type"] != "PREPAID":
            raise HTTPException(
                status_code=400,
                detail="Only PREPAID wallets can be topped up"
            )
        
        # Create top-up record
        top_up = supabase.table("wallet_top_ups").insert({
            "wallet_id": str(wallet_id),
            "amount": request.amount,
            "payment_method": request.payment_method,
            "status": "PENDING"
        }).execute()
        
        # TODO: Integrate with payment processor (Stripe)
        # For now, auto-approve and update wallet balance
        
        # Update wallet balance
        new_balance = wallet.data["balance"] + request.amount
        supabase.table("wallets")\
            .update({"balance": new_balance})\
            .eq("id", str(wallet_id))\
            .execute()
        
        # Mark top-up as completed
        supabase.table("wallet_top_ups")\
            .update({"status": "COMPLETED", "completed_at": "NOW()"})\
            .eq("id", top_up.data[0]["id"])\
            .execute()
        
        logger.info(f"💰 Wallet {wallet_id} topped up: ${request.amount}")
        
        return TopUpResponse(**top_up.data[0])
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Top-up failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wallets/{wallet_id}/convert-to-prepaid")
async def convert_to_prepaid(wallet_id: UUID, supabase=Depends(get_supabase)):
    """Convert a POSTPAID wallet to PREPAID."""
    try:
        result = supabase.table("wallets")\
            .update({"wallet_type": "PREPAID"})\
            .eq("id", str(wallet_id))\
            .execute()
        
        logger.info(f"✅ Converted wallet {wallet_id} to PREPAID")
        
        return {"message": "Wallet converted to PREPAID", "wallet_id": str(wallet_id)}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallets/{wallet_id}/top-ups", response_model=List[TopUpResponse])
async def list_top_ups(
    wallet_id: UUID,
    limit: int = 50,
    supabase=Depends(get_supabase)
):
    """List top-up history for a wallet."""
    try:
        result = supabase.table("wallet_top_ups")\
            .select("*")\
            .eq("wallet_id", str(wallet_id))\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()
        
        return [TopUpResponse(**row) for row in result.data]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Anomaly Management
# ============================================================================

@router.get("/anomalies", response_model=List[AnomalyResponse])
async def list_anomalies(
    user_id: Optional[UUID] = None,
    tenant_id: Optional[UUID] = None,
    resolved: Optional[bool] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    supabase=Depends(get_supabase)
):
    """List spend anomalies."""
    try:
        query = supabase.table("spend_anomalies")\
            .select("*")\
            .order("detected_at", desc=True)\
            .limit(limit)
        
        if user_id:
            query = query.eq("user_id", str(user_id))
        if tenant_id:
            query = query.eq("tenant_id", str(tenant_id))
        if resolved is not None:
            query = query.eq("resolved", resolved)
        if severity:
            query = query.eq("severity", severity)
        
        result = query.execute()
        
        return [AnomalyResponse(**row) for row in result.data]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomalies/{anomaly_id}/acknowledge")
async def acknowledge_anomaly(
    anomaly_id: UUID,
    resolution_note: Optional[str] = None,
    supabase=Depends(get_supabase)
):
    """Acknowledge and resolve an anomaly."""
    try:
        result = supabase.table("spend_anomalies")\
            .update({
                "resolved": True,
                "resolved_at": "NOW()",
                "resolution_note": resolution_note
            })\
            .eq("id", str(anomaly_id))\
            .execute()
        
        logger.info(f"✅ Acknowledged anomaly {anomaly_id}")
        
        return {"message": "Anomaly acknowledged", "anomaly_id": str(anomaly_id)}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomalies/train-model/{user_id}")
async def train_anomaly_model(user_id: UUID):
    """Train or retrain anomaly detection model for a user."""
    try:
        success = await spend_anomaly_detector.train_model(str(user_id), force_retrain=True)
        
        if success:
            return {"message": f"Model trained successfully for user {user_id}"}
        else:
            raise HTTPException(
                status_code=400,
                detail="Insufficient data to train model (need 10+ historical samples)"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Model training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
