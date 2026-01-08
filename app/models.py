# app/models.py
from pydantic import BaseModel, Field
from typing import Optional, Dict

class AuthorizeRequest(BaseModel):
    actor_id: str = Field(..., description="ID del agente o usuario que ejecuta")
    cost_center_id: str = Field(..., description="ID del proyecto o centro de costes")
    provider: str = Field(..., description="openai, anthropic, etc.")
    model: str = Field(..., description="gpt-4, claude-3, etc.")
    max_amount: float = Field(..., gt=0, description="Límite de gasto autorizado")
    currency: str = Field("EUR", description="Moneda del límite")
    metadata: Optional[Dict] = Field(default_factory=dict)
    
    # DATOS PARA ESTIMACIÓN INTELIGENTE
    est_input_tokens: int = Field(0, description="Deprecated: Use input_unit_count")
    input_unit_count: float = Field(0.0, description="Cantidad de unidades de entrada (Tokens, Caracteres, Minutos, Imagenes)")
    # Opcional: Enviar hash del prompt o categoría para buscar similares en historia
    prompt_fingerprint: Optional[str] = None

class AuthorizeResponse(BaseModel):
    decision: str # APPROVED, DENIED
    aut_token: Optional[str] = None
    reason_code: Optional[str] = None
    authorization_id: str
    
    # NUEVOS CAMPOS PARA SMART ROUTING
    suggested_model: Optional[str] = None
    suggested_provider: Optional[str] = None
    estimated_cost: Optional[float] = None # Para mostrar al usuario