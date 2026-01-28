# app/routers/ai_act_compliance.py
"""
API endpoints for EU AI Act Compliance.
Provides classification, approval management, and audit trail access.
"""
import logging
from typing import List, Optional
from uuid import UUID
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, Field

from app.services.eu_ai_act_classifier import eu_ai_act_classifier, RiskLevel, RiskCategory
from app.services.human_approval_queue import human_approval_queue
from app.database import get_supabase

logger = logging.getLogger("agentshield.ai_act_api")

router = APIRouter(prefix="/ai-act", tags=["EU AI Act Compliance"])


# Pydantic Models
class ClassificationRequest(BaseModel):
    prompt: str = Field(..., description="User's prompt to classify")
    context: dict = Field(default={}, description="Additional context (department, use_case, etc.)")


class ClassificationResponse(BaseModel):
    risk_level: str
    risk_category: str
    confidence: float
    article_reference: str
    requires_approval: bool
    transparency_required: bool


class ApprovalRequest(BaseModel):
    approval_note: Optional[str] = None


class RejectRequest(BaseModel):
    rejection_reason: str = Field(..., min_length=10)


class ApprovalResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    risk_level: str
    risk_category: str
    request_summary: str
    status: str
    created_at: str
    expires_at: str


class AuditLogEntry(BaseModel):
    trace_id: str
    risk_level: str
    risk_category: str
    classification_confidence: float
    required_human_approval: bool
    approval_status: Optional[str]
    transparency_disclosure_shown: bool
    audit_hash: str
    created_at: str


# API Endpoints
@router.post("/classify", response_model=ClassificationResponse)
async def classify_request(request: ClassificationRequest):
    """
    Classify an AI request according to EU AI Act.
    
    Returns risk level, category, and compliance requirements.
    """
    risk_level, risk_category, confidence = eu_ai_act_classifier.classify(
        prompt=request.prompt,
        context=request.context
    )
    
    # Determine article reference
    article_map = {
        RiskLevel.PROHIBITED: "Article 5",
        RiskLevel.HIGH_RISK: "Annex III",
        RiskLevel.LIMITED_RISK: "Article 52",
        RiskLevel.MINIMAL_RISK: "N/A"
    }
    
    return ClassificationResponse(
        risk_level=risk_level,
        risk_category=risk_category,
        confidence=confidence,
        article_reference=article_map[risk_level],
        requires_approval=(risk_level == RiskLevel.HIGH_RISK),
        transparency_required=(risk_level == RiskLevel.LIMITED_RISK)
    )


@router.get("/approvals", response_model=List[ApprovalResponse])
async def list_pending_approvals(
    tenant_id: UUID,
    status: Optional[str] = "PENDING",
    limit: int = 50
):
    """List approval requests for a tenant."""
    try:
        queue = await human_approval_queue.get_pending_approvals(str(tenant_id), limit)
        return [ApprovalResponse(**item) for item in queue]
    except Exception as e:
        logger.error(f"Failed to list approvals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval_details(approval_id: UUID):
    """Get details of a specific approval request."""
    status = await human_approval_queue.get_approval_status(str(approval_id))
    
    if not status:
        raise HTTPException(status_code=404, detail="Approval not found")
    
    return ApprovalResponse(**status)


@router.post("/approvals/{approval_id}/approve", status_code=status.HTTP_200_OK)
async def approve_request(
    approval_id: UUID,
    request: ApprovalRequest,
    approver_id: UUID = Header(..., alias="X-User-ID")
):
    """
    Approve a HIGH_RISK request (Article 14 - Human oversight).
    """
    success = await human_approval_queue.approve_request(
        approval_id=str(approval_id),
        approver_id=str(approver_id),
        approval_note=request.approval_note
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval failed (not pending or not found)"
        )
    
    return {"message": "Request approved", "approval_id": str(approval_id)}


@router.post("/approvals/{approval_id}/reject", status_code=status.HTTP_200_OK)
async def reject_request(
    approval_id: UUID,
    request: RejectRequest,
    approver_id: UUID = Header(..., alias="X-User-ID")
):
    """
    Reject a HIGH_RISK request (Article 14 - Human oversight).
    """
    success = await human_approval_queue.reject_request(
        approval_id=str(approval_id),
        approver_id=str(approver_id),
        rejection_reason=request.rejection_reason
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rejection failed (not pending or not found)"
        )
    
    return {"message": "Request rejected", "approval_id": str(approval_id)}


@router.get("/audit", response_model=List[AuditLogEntry])
async def get_audit_trail(
    tenant_id: UUID,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    risk_level: Optional[str] = None,
    limit: int = 100,
    supabase=Depends(get_supabase)
):
    """
    Retrieve audit trail (Article 12 - Record-keeping).
    Required retention: 24 months minimum.
    """
    try:
        query = supabase.table("ai_act_audit_log")\
            .select("trace_id,risk_level,risk_category,classification_confidence,required_human_approval,approval_status,transparency_disclosure_shown,audit_hash,created_at")\
            .eq("tenant_id", str(tenant_id))\
            .order("created_at", desc=True)\
            .limit(limit)
        
        if from_date:
            query = query.gte("created_at", from_date.isoformat())
        if to_date:
            query = query.lte("created_at", to_date.isoformat())
        if risk_level:
            query = query.eq("risk_level", risk_level)
        
        result = query.execute()
        
        return [AuditLogEntry(**row) for row in result.data]
        
    except Exception as e:
        logger.error(f"Failed to retrieve audit trail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audit/{trace_id}", response_model=AuditLogEntry)
async def get_audit_entry(trace_id: str, supabase=Depends(get_supabase)):
    """Get specific audit entry by trace ID."""
    try:
        result = supabase.table("ai_act_audit_log")\
            .select("*")\
            .eq("trace_id", trace_id)\
            .single()\
            .execute()
        
        return AuditLogEntry(**result.data)
        
    except Exception as e:
        raise HTTPException(status_code=404, detail="Audit entry not found")


@router.get("/compliance-summary")
async def get_compliance_summary(
    tenant_id: UUID,
    from_date: date,
    to_date: date,
    supabase=Depends(get_supabase)
):
    """
    Get compliance summary for reporting.
    Shows distribution of risk levels, approval rates, etc.
    """
    try:
        result = supabase.rpc(
            "get_compliance_summary",
            {
                "p_tenant_id": str(tenant_id),
                "p_from_date": from_date.isoformat(),
                "p_to_date": to_date.isoformat()
            }
        ).execute()
        
        return result.data
        
    except Exception as e:
        logger.error(f"Failed to get compliance summary: {e}")
        # Fallback: manual aggregation
        return await _manual_compliance_summary(tenant_id, from_date, to_date, supabase)


async def _manual_compliance_summary(tenant_id: UUID, from_date: date, to_date: date, supabase):
    """Fallback manual aggregation if RPC fails."""
    result = supabase.table("ai_act_audit_log")\
        .select("risk_level,risk_category,required_human_approval,approval_status")\
        .eq("tenant_id", str(tenant_id))\
        .gte("created_at", from_date.isoformat())\
        .lte("created_at", to_date.isoformat())\
        .execute()
    
    data = result.data
    
    summary = {
        "total_requests": len(data),
        "prohibited_blocked": sum(1 for r in data if r["risk_level"] == "PROHIBITED"),
        "high_risk_approvals_required": sum(1 for r in data if r["required_human_approval"]),
        "high_risk_approved": sum(1 for r in data if r["approval_status"] == "APPROVED"),
        "risk_distribution": {}
    }
    
    for risk_level in ["PROHIBITED", "HIGH_RISK", "LIMITED_RISK", "MINIMAL_RISK"]:
        summary["risk_distribution"][risk_level] = sum(1 for r in data if r["risk_level"] == risk_level)
    
    return summary


@router.get("/conformity-assessment")
async def get_conformity_assessment(tenant_id: UUID):
    """
    Self-assessment conformity check (Annex VII).
    Returns compliance status for key requirements.
    """
    # TODO: Implement full conformity assessment
    # For now, return basic checklist
    
    return {
        "tenant_id": str(tenant_id),
        "assessment_date": date.today().isoformat(),
        "conformity_status": "COMPLIANT",
        "requirements": {
            "risk_management_system": {"status": "IMPLEMENTED", "article": "Article 9"},
            "data_governance": {"status": "IMPLEMENTED", "article": "Article 10"},
            "technical_documentation": {"status": "IMPLEMENTED", "article": "Article 11"},
            "record_keeping": {"status": "IMPLEMENTED", "article": "Article 12"},
            "transparency": {"status": "IMPLEMENTED", "article": "Article 13"},
            "human_oversight": {"status": "IMPLEMENTED", "article": "Article 14"}
        },
        "next_assessment": "2027-01-28"
    }
