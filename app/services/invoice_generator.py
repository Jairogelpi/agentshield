# app/services/invoice_generator.py
import io
from datetime import datetime
from typing import Any, Dict

from fpdf import FPDF


class CorporateInvoicePDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(50, 50, 50)
        self.cell(0, 10, "AgentShield | Internal Chargeback", 0, 1, "L")
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, "AI Governance & Compute Ledger", 0, 1, "L")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(
            0,
            10,
            f"Page {self.page_no()} | Confidential Financial Document | AgentShield OS",
            0,
            0,
            "C",
        )

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 11)
        self.set_fill_color(245, 245, 245)
        self.set_text_color(0, 0, 0)
        self.cell(0, 8, f"  {title}", 0, 1, "L", fill=True)
        self.ln(4)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def generate_department_invoice_pdf(payload: dict[str, Any]) -> bytes:
    pdf = CorporateInvoicePDF()
    pdf.add_page()

    # --- INFO BLOCK ---
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 8, f"INTERNAL INVOICE | PERIOD: {payload['period']}", 0, 1, "L")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Invoice ID: {payload['invoice_id']}", 0, 1, "L")
    pdf.cell(0, 6, f"Cost Center: {payload['cost_center_id']}", 0, 1, "L")
    pdf.cell(
        0, 6, f"Settlement Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", 0, 1, "L"
    )
    pdf.ln(8)

    # --- EXECUTIVE SUMMARY ---
    t = payload["totals"]
    pdf.section_title("EXECUTIVE SUMMARY & ROI")

    rows = [
        ("Gross Model Consumption (Market Baseline)", _money(t["gross_usd"])),
        ("Efficiency Savings (AgentShield Arbitrage)", f"-{_money(t['savings_usd'])}"),
        ("Net Compute Cost", _money(t["actual_usd"])),
        ("Knowledge Contribution Credits", f"-{_money(t['knowledge_credits_usd'])}"),
        ("TOTAL CHARGEBACK PAYABLE", _money(t["net_payable_usd"])),
    ]

    pdf.set_font("Helvetica", "", 10)
    for label, val in rows:
        is_total = "TOTAL" in label
        if is_total:
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(0, 100, 0)  # Dark green for net

        pdf.cell(140, 7, label, 0, 0, "L")
        pdf.cell(50, 7, val, 0, 1, "R")

        if is_total:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(0, 0, 0)

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(
        0,
        6,
        f"Stats: {t['requests']:,} requests | {t['tokens']:,} tokens processed globally.",
        0,
        1,
        "L",
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    # --- LINE ITEMS ---
    pdf.section_title("DETAILED COST BREAKDOWN")
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(110, 7, "Description", 1, 0, "L", True)
    pdf.cell(40, 7, "Volume", 1, 0, "C", True)
    pdf.cell(40, 7, "Subtotal", 1, 1, "R", True)

    pdf.set_font("Helvetica", "", 9)
    for li in payload["line_items"]:
        pdf.cell(110, 7, li["desc"], 1, 0, "L")
        pdf.cell(40, 7, str(li["qty"]), 1, 0, "C")
        pdf.cell(40, 7, _money(li["total_usd"]), 1, 1, "R")
    pdf.ln(8)

    # --- SUSTAINABILITY ---
    c = payload.get("carbon", {})
    pdf.section_title("GREEN AI & ESG IMPACT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        0,
        6,
        f"By leveraging AgentShield Green Routing, your department avoided {c.get('saved_g', 0) / 1000:.3f} kg of CO2 emissions. "
        f"Actual footprint: {c.get('actual_g', 0) / 1000:.3f} kg CO2e.",
    )
    pdf.ln(6)

    # --- AUDIT TRAIL ---
    a = payload.get("audit", {})
    pdf.section_title("CRYPTOGRAPHIC AUDIT TRAIL")
    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(
        0,
        4,
        f"Governance Policy Hash: {a.get('policy_hash', '-')}\n"
        f"Proof of Integrity (Sample Receipts):\n{', '.join(a.get('sample_receipts', []))}",
    )

    return pdf.output()
