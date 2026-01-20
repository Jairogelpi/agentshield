# app/services/invoice_service.py
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from app.db import supabase

logger = logging.getLogger("agentshield.invoice")


async def compute_invoice(tenant_id: str, cost_center_id: str, month_str: str) -> dict[str, Any]:
    """
    Agrega recibos, eventos de ledger y métricas de carbono para un mes dado.
    PROHIBIDO EL USO DE DATOS MOCK (Tenant Name, Credits, etc.)
    """
    try:
        # Calcular rango de fechas
        year, month = map(int, month_str.split("-"))
        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"

        # 1. Obtener Datos Maestros (REAL-TIME DB)
        tenant_res = (
            supabase.table("tenants").select("name").eq("id", tenant_id).maybe_single().execute()
        )
        tenant_name = (
            tenant_res.data.get("name", "Unknown Corp") if tenant_res.data else "Unknown Corp"
        )

        dept_res = (
            supabase.table("departments")
            .select("name")
            .eq("id", cost_center_id)
            .maybe_single()
            .execute()
        )
        dept_name = (
            dept_res.data.get("name", f"CC {cost_center_id[:8]}") if dept_res.data else "Generic CC"
        )

        # 2. Obtener Totales de Recibos (Compute Spend)
        receipts_query = (
            supabase.table("receipts")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("cost_center_id", cost_center_id)
            .gte("created_at", start_date)
            .lt("created_at", end_date)
            .execute()
        )

        receipts = receipts_query.data or []

        # Cálculos Agregados
        gross_usd = sum(float(r.get("cost_gross", 0) or 0) for r in receipts)
        actual_usd = sum(float(r.get("cost_real", 0) or 0) for r in receipts)
        savings_usd = sum(float(r.get("savings_usd", 0) or 0) for r in receipts)

        requests_count = len(receipts)
        tokens_count = sum(int(r.get("tokens", 0) or 0) for r in receipts)

        # 3. Ingresos por Conocimiento (Real aggregation from internal_ledger)
        # Consultamos créditos liquidados para este cost_center en este periodo
        ledger_query = (
            supabase.table("ledger_settlements")
            .select("amount_usd")
            .eq("receiver_cost_center_id", cost_center_id)
            .gte("created_at", start_date)
            .lt("created_at", end_date)
            .execute()
        )

        knowledge_credits_usd = sum(
            float(l.get("amount_usd", 0)) for l in (ledger_query.data or [])
        )

        # 4. Carbono (Agregado Real)
        co2_gross = sum(float(r.get("co2_gross_g", 0) or 0) for r in receipts)
        co2_actual = sum(float(r.get("co2_actual_g", 0) or 0) for r in receipts)
        co2_saved = max(0, co2_gross - co2_actual)

        # 5. Datos de Auditoría
        sample_receipts = [r["id"] for r in receipts[:5]]
        policy_hash = (
            receipts[0]
            .get("full_receipt", {})
            .get("governance", {})
            .get("policy_version_hash", "N/A")
            if receipts
            else "N/A"
        )

        return {
            "invoice_id": f"INV-{year}{month:02d}-{cost_center_id[:8].upper()}",
            "period": month_str,
            "tenant_name": tenant_name,
            "dept_name": dept_name,
            "cost_center_id": cost_center_id,
            "totals": {
                "gross_usd": round(gross_usd, 4),
                "actual_usd": round(actual_usd, 4),
                "savings_usd": round(savings_usd, 4),
                "knowledge_credits_usd": round(knowledge_credits_usd, 4),
                "net_payable_usd": round(actual_usd - knowledge_credits_usd, 4),
                "requests": requests_count,
                "tokens": tokens_count,
            },
            "carbon": {
                "gross_g": round(co2_gross, 2),
                "actual_g": round(co2_actual, 2),
                "saved_g": round(co2_saved, 2),
            },
            "line_items": [
                {
                    "desc": f"AI Compute Cluster - {dept_name}",
                    "qty": f"{requests_count} calls",
                    "total_usd": round(actual_usd, 4),
                },
                {
                    "desc": "Knowledge Contribution Royalty",
                    "qty": "credits",
                    "total_usd": -round(knowledge_credits_usd, 4),
                }
                if knowledge_credits_usd > 0
                else None,
            ],
            "audit": {"policy_hash": policy_hash, "sample_receipts": sample_receipts},
        }
    except Exception as e:
        logger.error(f"Failed to compute invoice: {e}")
        raise
