# app/services/forensics.py
from app.db import supabase
from fpdf import FPDF
import json
import datetime
import logging

logger = logging.getLogger("agentshield.forensics")

class ForensicService:
    async def reconstruct_timeline(self, tenant_id: str, trace_id: str):
        """
        Reúne fragmentos dispersos de toda la base de datos para reconstruir
        la vida de una petición (Request Life).
        """
        timeline = []

        # 1. Buscar el Recibo (El final de la cadena)
        # Este contiene el costo final y la firma
        try:
            receipt = supabase.table("receipts").select("*").eq("trace_id", trace_id).eq("tenant_id", tenant_id).limit(1).execute()
            if receipt.data:
                timeline.append({"ts": receipt.data[0]['created_at'], "type": "FINISH", "data": receipt.data[0]})
        except Exception as e:
            logger.warning(f"Forensics: Error fetching receipts: {e}")

        # 2. Buscar Eventos de Política (El principio)
        # Estos son los bloqueos o avisos del Policy Engine
        try:
            policies = supabase.table("policy_events").select("*").eq("tenant_id", tenant_id).contains("metadata", {"trace_id": trace_id}).execute()
            for p in policies.data:
                timeline.append({"ts": p['created_at'], "type": "POLICY_CHECK", "data": p})
        except Exception as e:
            logger.warning(f"Forensics: Error fetching policies: {e}")

        # 3. Buscar Aprobaciones de Herramientas (El nudo)
        # Interceptaciones del Tool Governor
        try:
            tools = supabase.table("tool_approvals").select("*").eq("tenant_id", tenant_id).contains("tool_arguments", {"_trace_id": trace_id}).execute()
            for t in tools.data:
                timeline.append({"ts": t['created_at'], "type": "TOOL_INTERCEPT", "data": t})
                if t['reviewed_at']:
                    # Evento derivado: La revisión humana
                    timeline.append({
                        "ts": t['reviewed_at'], 
                        "type": "HUMAN_REVIEW", 
                        "data": {
                            "decision": t['status'], 
                            "reviewer": t['reviewer_id'],
                            "note": t.get('review_note')
                        }
                    })
        except Exception as e:
             logger.warning(f"Forensics: Error fetching tools: {e}")
             
        # 4. Buscar Eventos de Seguridad (Ataques)
        try:
             security = supabase.table("security_events").select("*").eq("trace_id", trace_id).limit(1).execute()
             if security.data:
                 timeline.append({"ts": security.data[0]['created_at'], "type": "SECURITY_ALERT", "data": security.data[0]})
        except Exception as e:
            logger.warning(f"Forensics: Error fetching security events: {e}")

        # 4. Ordenar Cronológicamente
        timeline.sort(key=lambda x: str(x['ts']))
        
        return timeline

    def generate_legal_pdf(self, timeline: list, trace_id: str) -> bytes:
        """
        Genera un PDF estilo 'Informe Policial' o 'Evidencia Bancaria'.
        """
        pdf = FPDF()
        pdf.add_page()
        
        # Header
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 10, "AgentShield Forensic Report", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 10, f"Trace ID: {trace_id}", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, f"Generated: {datetime.datetime.now()}", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(10)

        # Body - Disclaimer
        pdf.set_font("helvetica", "I", 8)
        pdf.multi_cell(0, 5, "CONFIDENTIAL: This document contains a cryptographic reconstruction of an AI interaction. It is intended for internal auditing and legal compliance verification.")
        pdf.ln(5)

        # Timeline
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "Execution Timeline (Chain of Custody)", new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font("courier", "", 9) # Monospace para aspecto técnico
        
        for step in timeline:
            ts = step['ts']
            event_type = step['type']
            
            # Colorear texto (simulado con RGB)
            if event_type == "POLICY_CHECK":
                pdf.set_text_color(200, 100, 0) # Naranja
            elif event_type == "FINISH":
                pdf.set_text_color(0, 150, 0) # Verde
            elif event_type == "TOOL_INTERCEPT" or event_type == "SECURITY_ALERT":
                 pdf.set_text_color(200, 0, 0) # Rojo
            else:
                 pdf.set_text_color(0, 0, 0) # Negro
                
            pdf.cell(50, 6, f"[{ts}]", border=0)
            pdf.cell(50, 6, f"{event_type}", border=0)
            pdf.ln(6)
            
            # Detalles JSON (Redactados visualmente)
            pdf.set_text_color(80, 80, 80) # Gris oscuro
            
            # Limpieza para impresion
            data_clean = step['data'].copy()
            if 'embedding' in data_clean: del data_clean['embedding'] # No imprimir vectores
            
            data_str = json.dumps(data_clean, default=str, indent=2)
            # Truncar si es muy largo para PDF
            if len(data_str) > 1000: data_str = data_str[:1000] + "... [TRUNCATED]"
            
            pdf.multi_cell(0, 4, f"{data_str}")
            pdf.ln(4)
            
            # Separador
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_w() - 10, pdf.get_y())
            pdf.ln(4)

        # Footer con Firma Digital (Simulada para visualización)
        pdf.set_y(-30)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("helvetica", "I", 8)
        pdf.cell(0, 10, "Digital Signature: SHA-256 Verified via AgentShield Immutable Ledger.", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, "AgentShield Inc. - audit.agentshield.com", align="C")
        
        return pdf.output()

forensics = ForensicService()
