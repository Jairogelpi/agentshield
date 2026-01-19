# app/models.py
from pydantic import BaseModel, Field
from typing import Optional, Dict
from enum import Enum
from datetime import datetime

class TenantRegion(str, Enum):
    EU = "eu"
    US = "us"

class AIUseCase(str, Enum):
    # Categorías basadas en EU AI Act Annex III
    GENERAL_PURPOSE = "general_purpose" # Chatbots, Coding (Riesgo Mínimo)
    HR_RECRUITMENT = "hr_recruitment"   # Filtrado de CVs (Alto Riesgo)
    CREDIT_SCORING = "credit_scoring"   # Finanzas (Alto Riesgo)
    MEDICAL_ADVICE = "medical_advice"   # Salud (Alto Riesgo)
    BIOMETRIC_ID = "biometric_id"       # Identificación (Riesgo Inaceptable/Alto)
    LEGAL_ASSIST = "legal_assist"       # Justicia (Alto Riesgo)

class FunctionConfig(BaseModel):
    """
    Configuración dinámica por función (Function-ID).
    Permite 'Model Swapping', control de presupuesto y enrutamiento híbrido.
    """
    tenant_id: str
    function_id: str
    budget_daily: float = 0.0     # 0.0 = Sin límite
    current_spend_daily: float = 0.0
    is_active: bool = True
    force_model: Optional[str] = None
    force_provider: Optional[str] = None
    upstream_url: Optional[str] = None # Para enrutamiento local/privado
    use_case: str = "general_purpose" # Categoría legal, similar a AIUseCase pero string libre o enum
    last_used: Optional[datetime] = None

    class Config:
        # Esto permite que Pydantic lea datos que vengan de la DB si en el futuro usas ORM
        from_attributes = True

class SovereignConfig(BaseModel):
    share_knowledge: bool = False
    buy_knowledge: bool = True
    revenue_share_target: float = 0.5
    # NUEVO: Control granular por tenant para el arbitraje automático
    smart_routing_enabled: bool = True

class AuthorizeRequest(BaseModel):
    actor_id: str = Field(..., description="ID del agente o usuario que ejecuta")
    cost_center_id: str = Field(..., description="ID del proyecto o centro de costes")
    # MODIFICAR: Hacer provider/model opcionales si se usa function_id
    provider: str = Field("default", description="openai, anthropic, etc.")
    model: str = Field("default", description="gpt-4, claude-3, etc.")
    
    # NUEVO CAMPO OPCIONAL
    function_id: Optional[str] = Field(None, description="ID de configuración remota (Sobreescribe parámetros)")

    # NUEVO CAMPO: Obligatorio para compliance
    use_case: AIUseCase = Field(
        default=AIUseCase.GENERAL_PURPOSE, 
        description="Categoría legal del uso según EU AI Act"
    )
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
    execution_mode: str = "ACTIVE" # ACTIVE, SHADOW_SIMULATION
    aut_token: Optional[str] = None
    reason_code: Optional[str] = None
    authorization_id: str
    
    # NUEVOS CAMPOS PARA SMART ROUTING
    suggested_model: Optional[str] = None
    suggested_provider: Optional[str] = None
    estimated_cost: Optional[float] = None # Para mostrar al usuario

class CostCenterBudgetUpdate(BaseModel):
    monthly_budget: float = Field(..., gt=0, description="Nuevo límite mensual para el centro de costes")