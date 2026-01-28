# app/services/hud.py
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class HudMetrics(BaseModel):
    request_id: str
    model_used: str
    provider: str
    latency_ms: int
    tokens_total: int
    cost_usd: float
    savings_usd: float
    co2_grams: float
    co2_saved_grams: float
    trust_score: int
    pii_redactions: int
    intent: str
    role: str | None = None
    active_rules: list | None = Field(default_factory=list)  # [NEW] List of strings


def _get_risk_badge(score: int) -> str:
    if score >= 80:
        return "🟢 LOW"
    if score >= 50:
        return "🟡 MED"
    return "🔴 HIGH"


def render_hud_markdown(metrics: HudMetrics) -> str:
    """
    Genera una tarjeta Markdown minimalista y compatible con OpenWebUI/LibreChat.
    """
    risk_badge = _get_risk_badge(metrics.trust_score)
    savings_pct = 0
    if (metrics.cost_usd + metrics.savings_usd) > 0:
        savings_pct = int((metrics.savings_usd / (metrics.cost_usd + metrics.savings_usd)) * 100)

    role_str = metrics.role or "Standard"

    # Diseño "Cockpit" compacto
    return (
        f"\n\n---\n"
        f"**🛡️ AgentShield HUD** | **Role:** `{role_str}` | **Trust:** `{metrics.trust_score}/100`  \n"
        f"**Savings:** `${metrics.savings_usd:.4f}` | **CO2 Saved:** `{metrics.co2_saved_grams:.2f}g`"
    )


def build_structured_event(metrics: HudMetrics) -> str:
    """
    Genera el evento SSE personalizado para tu frontend propio.
    """
    payload = {
        "type": "hud_update",
        "data": {
            "trace_id": metrics.request_id,
            "intent": metrics.intent,
            "financial": {
                "cost": metrics.cost_usd,
                "savings": metrics.savings_usd,
                "currency": "USD",
            },
            "sustainability": {
                "emitted": metrics.co2_grams,
                "avoided": metrics.co2_saved_grams,
                "unit": "grams_co2",
            },
            "security": {"trust_score": metrics.trust_score, "pii_count": metrics.pii_redactions},
            "performance": {
                "latency_ms": metrics.latency_ms,
                "model": metrics.model_used,
                "tokens": metrics.tokens_total,
                "role": metrics.role,
            },
            "active_rules": metrics.active_rules or [],  # [NEW]
        },
    }
    # Formato SSE estándar: event: nombre \n data: json \n\n
    return f"event: agentshield.hud\ndata: {json.dumps(payload)}\n\n"
