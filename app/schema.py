from pydantic import BaseModel, Field
from typing import List, Optional, Any

class DecisionContext(BaseModel):
    """
    El Estado Global de una Petición en el Decision Graph.
    Acumula decisiones de cada 'Gate' (Identity, Risk, Carbon, etc.)
    """
    # 1. Identity
    trace_id: str
    tenant_id: str
    user_id: str
    dept_id: Optional[str]
    email: Optional[str] = None # Mantenemos email para el recibo
    
    # 2. Intent & Budget
    intent: str = "GENERAL"
    
    # 3. Risk State
    trust_score: int = 100
    risk_mode: str = "normal" # normal, restricted, supervised
    
    # 4. Compliance State
    pii_redacted: bool = False
    
    # 5. Carbon State
    co2_estimated: float = 0.0
    green_routing_active: bool = False
    
    # 6. Execution State
    requested_model: str
    effective_model: str
    
    # Auditoría
    decision_log: List[str] = Field(default_factory=list)
    
    def log(self, gate: str, decision: str):
        self.decision_log.append(f"[{gate}] {decision}")
