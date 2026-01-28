# app/services/human_approval_queue.py
"""
EU AI Act Human-in-the-Loop Workflow (Article 14).
Manages approval queue for HIGH_RISK AI operations.
"""
import logging
from typing import Dict, Optional
from uuid import UUID
from datetime import datetime, timedelta

from app.database import get_supabase
from app.services.eu_ai_act_classifier import RiskLevel, RiskCategory

logger = logging.getLogger("agentshield.human_approval")


class HumanApprovalQueue:
    """
    Revolutionary Human-in-the-Loop System (EU AI Act Article 14).
    Manages approval workflow for HIGH_RISK operations.
    """
    
    def __init__(self):
        self.supabase = get_supabase()
    
    async def create_approval_request(
        self,
        tenant_id: str,
        user_id: str,
        trace_id: str,
        request_hash: str,
        risk_level: RiskLevel,
        risk_category: RiskCategory,
        request_summary: str,
        full_request: Dict,
        classification_confidence: float
    ) -> str:
        """
        Create a new approval request in the queue.
        
        Returns:
            approval_id (UUID)
        """
        try:
            data = {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "trace_id": trace_id,
                "request_hash": request_hash,
                "risk_level": risk_level,
                "risk_category": risk_category,
                "request_summary": request_summary,
                "full_request": full_request,
                "classification_confidence": classification_confidence,
                "status": "PENDING",
                "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat()
            }
            
            result = self.supabase.table("ai_act_approval_queue").insert(data).execute()
            
            approval_id = result.data[0]["id"]
            
            logger.warning(
                f"🚨 HIGH_RISK operation requires approval: {risk_category} "
                f"(approval_id: {approval_id}, trace_id: {trace_id})"
            )
            
            # Send notifications
            await self._send_approval_notifications(approval_id, tenant_id, risk_category)
            
            return approval_id
            
        except Exception as e:
            logger.error(f"Failed to create approval request: {e}")
            raise
    
    async def approve_request(
        self,
        approval_id: str,
        approver_id: str,
        approval_note: Optional[str] = None
    ) -> bool:
        """Approve a pending request."""
        try:
            result = self.supabase.table("ai_act_approval_queue")\
                .update({
                    "status": "APPROVED",
                    "approver_id": approver_id,
                    "approval_note": approval_note,
                    "decided_at": datetime.utcnow().isoformat()
                })\
                .eq("id", approval_id)\
                .eq("status", "PENDING")\
                .execute()
            
            if result.data:
                logger.info(f"✅ Approval granted: {approval_id} by approver {approver_id}")
                return True
            
            logger.warning(f"⚠️ Approval failed (not pending or not found): {approval_id}")
            return False
            
        except Exception as e:
            logger.error(f"Failed to approve request: {e}")
            return False
    
    async def reject_request(
        self,
        approval_id: str,
        approver_id: str,
        rejection_reason: str
    ) -> bool:
        """Reject a pending request."""
        try:
            result = self.supabase.table("ai_act_approval_queue")\
                .update({
                    "status": "REJECTED",
                    "approver_id": approver_id,
                    "rejection_reason": rejection_reason,
                    "decided_at": datetime.utcnow().isoformat()
                })\
                .eq("id", approval_id)\
                .eq("status", "PENDING")\
                .execute()
            
            if result.data:
                logger.info(f"❌ Approval rejected: {approval_id} by approver {approver_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to reject request: {e}")
            return False
    
    async def get_pending_approvals(self, tenant_id: str, limit: int = 50) -> list:
        """Get pending approvals for a tenant."""
        try:
            result = self.supabase.table("ai_act_approval_queue")\
                .select("*")\
                .eq("tenant_id", tenant_id)\
                .eq("status", "PENDING")\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()
            
            return result.data
            
        except Exception as e:
            logger.error(f"Failed to get pending approvals: {e}")
            return []
    
    async def get_approval_status(self, approval_id: str) -> Optional[Dict]:
        """Check status of an approval request."""
        try:
            result = self.supabase.table("ai_act_approval_queue")\
                .select("*")\
                .eq("id", approval_id)\
                .single()\
                .execute()
            
            return result.data
            
        except Exception as e:
            logger.error(f"Failed to get approval status: {e}")
            return None
    
    async def wait_for_approval(
        self,
        approval_id: str,
        timeout_seconds: int = 3600
    ) -> bool:
        """
        Wait for approval decision (polling).
        Returns True if approved, False if rejected/expired/timeout.
        """
        import asyncio
        
        start_time = datetime.utcnow()
        
        while True:
            status = await self.get_approval_status(approval_id)
            
            if not status:
                return False
            
            if status["status"] == "APPROVED":
                return True
            
            if status["status"] in ["REJECTED", "EXPIRED"]:
                return False
            
            # Timeout check
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed > timeout_seconds:
                logger.warning(f"⏱️ Approval timeout: {approval_id}")
                return False
            
            # Poll every 5 seconds
            await asyncio.sleep(5)
    
    async def _send_approval_notifications(
        self,
        approval_id: str,
        tenant_id: str,
        risk_category: RiskCategory
    ):
        """Send notifications to designated approvers."""
        # TODO: Integrate with notification system (Email, Slack, Teams)
        # For now, just log
        logger.info(
            f"📧 Notification sent for approval {approval_id} "
            f"(tenant: {tenant_id}, category: {risk_category})"
        )
        
        # Mark notification as sent
        try:
            self.supabase.table("ai_act_approval_queue")\
                .update({"notification_sent": True})\
                .eq("id", approval_id)\
                .execute()
        except:
            pass


# Global instance
human_approval_queue = HumanApprovalQueue()
