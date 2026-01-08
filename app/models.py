# app/models.py
from pydantic import BaseModel, Field
from typing import Optional, Dict

class AuthorizeRequest(BaseModel):
    actor_id: str = Field(..., description="ID del agente o usuario que ejecuta")
    cost_center_id: str = Field(..., description="ID del proyecto o centro de costes")
    provider: str = Field(..., description="openai, anthropic, etc.")
    model: str = Field(..., description="gpt-4, claude-3, etc.")
    max_amount: float = Field(..., gt=0, description="Límite máximo de gasto estimado")
    currency: str = Field("EUR", description="Moneda del límite")
    metadata: Optional[Dict] = Field(default_factory=dict)

class AuthorizeResponse(BaseModel):
    decision: str # APPROVED, DENIED
    aut_token: Optional[str] = None
    reason_code: Optional[str] = None
    authorization_id: str