# app/schema.py
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid

class AgentShieldContext(BaseModel):
    """
    Objetivo de Contexto Unificado.
    Se genera en el Middleware de Identidad y viaja hasta el Recibo Forense.
    """
    # Identidad (Cargado desde JWT)
    tenant_id: str
    user_id: str
    dept_id: str
    email: str
    role: str = "employee"
    
    # Estado de Gobierno (Calculado por Policy Engine)
    trust_score: int = Field(default=100, description="Nivel de confianza del usuario (0-100)")
    policy_mode: str = Field(default="ENFORCE", description="SHADOW o ENFORCE")
    data_classification: str = Field(default="INTERNAL", description="Nivel de datos permitido (PUBLIC, INTERNAL, CONFIDENTIAL)")
    
    # Trazabilidad
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_ip: Optional[str] = None
    
    class Config:
        # Permite usar este modelo en otras clases Pydantic de forma laxa
        extra = "ignore" 
