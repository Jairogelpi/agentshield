# app/services/file_guardian.py
import logging
import re
import io
import json
from typing import Optional, List, Tuple
from fastapi import UploadFile, HTTPException
from app.db import supabase
from app.services.safe_logger import safe_logger

# Librerías de IA Local Eficiente (Lazy import would be better but global for initialization)
try:
    from optimum.onnxruntime import ORTModelForSequenceClassification
    from transformers import pipeline
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

logger = logging.getLogger("agentshield.file_guardian")

class FileGuardian:
    """
    🛡️ Smart Semantic Guardian: Regex + Zero-Shot Classification Local.
    """
    
    def __init__(self):
        self.ai_enabled = False
        self.classifier = None
        
        if AI_AVAILABLE:
            try:
                logger.info("🧠 Initializing Local Semantic Guardian (ONNX)...")
                # Load optimized small model for zero-shot
                self.classifier = pipeline(
                    "zero-shot-classification",
                    model="valhalla/distilbart-mnli-12-1", 
                    device=-1 # CPU
                )
                self.ai_enabled = True
                logger.info("✅ Semantic Guardian Ready.")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load AI model: {e}. Falling back to Regex-Only.")
                self.ai_enabled = False
        
        # Mapping: Policy Category -> Regex Patterns
        self.category_patterns = {
            "INVOICE": [r"(?i)factura", r"(?i)invoice", r"(?i)iban", r"(?i)swift", r"(?i)total\s*a\s*pagar"],
            "PAYSLIP": [r"(?i)nómina", r"(?i)salario", r"(?i)payslip", r"(?i)sueldo"],
            "FINANCIAL_REPORT": [r"(?i)balance", r"(?i)p&l", r"(?i)ganancias", r"(?i)ebitda"],
            "DNI": [r"(?i)dni", r"(?i)passport", r"(?i)pasaporte", r"(?i)nif"]
        }

    async def inspect_and_filter(self, file: UploadFile, user_id: str, tenant_id: str, dept_id: Optional[str] = None):
        """
        Main entry point. Checks file against active policies using Hybrid Engine.
        """
        if not file.filename:
            return True
            
        filename = file.filename
        
        # 0. DoS Protection: Size Limit (10MB)
        MAX_SIZE = 10 * 1024 * 1024
        
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        
        if size > MAX_SIZE:
             logger.warning(f"File {filename} blocked due to size {size} > {MAX_SIZE}")
             raise HTTPException(413, f"File too large. Maximum allowed size is {MAX_SIZE/1024/1024}MB.")

        # 1. Fetch Active Policies
        try:
            res = supabase.table("policies")\
                .select("id, name, rules, mode, target_dept_id")\
                .eq("tenant_id", tenant_id)\
                .eq("action", "BLOCK_UPLOAD")\
                .eq("is_active", True)\
                .execute()
            policies = res.data or []
        except Exception as e:
            logger.error(f"Failed to fetch policies: {e}")
            policies = [] # Fail open? or Fail close? Let's assume fail open if DB down to avoid locking users, but log error.

        if not policies:
            return True

        # 2. Extract Text (If possible)
        # Assuming text/md/csv/code. For PDF, we would need pypdf (skipped for now as per instructions to mock text extraction logic)
        try:
            content = await file.read()
            await file.seek(0)
            text = content.decode("utf-8", errors="ignore")
        except:
            # If binary/unreadable, we can't semantically scan.
            # Only blocks based on filename extension (checked later) or fallback.
            text = ""

        # 3. Check Policies
        for policy in policies:
            # Dept Check
            p_dept = policy.get('target_dept_id')
            if p_dept and str(p_dept) != str(dept_id):
                continue
            
            rules = policy.get('rules', {})
            blocked_cats = rules.get('block_categories', [])
            
            # Hybrid Check per Category
            for cat in blocked_cats:
                 # Map internal Category -> Regex
                 patterns = self.category_patterns.get(cat, [])
                 if not patterns: continue 
                 
                 # Quick Scan
                 if self._quick_scan(text, patterns) or self._quick_scan(filename, patterns):
                     # Potential Hit
                     
                     # Semantic Verify (if AI enabled and text available)
                     is_real = True
                     if self.ai_enabled and text and len(text) > 10:
                         is_real = self._semantic_verify(text, cat)
                         if not is_real:
                             logger.info(f"🧠 AI Saved False Positive: '{filename}' matched {cat} regex but semantic check passed.")
                     
                     if is_real:
                         reason = f"Detected sensitive content: {cat}"
                         await self._audit_block(tenant_id, policy['id'], user_id, filename, cat, reason)
                         
                         if policy.get('mode') == 'ENFORCE':
                             raise HTTPException(403, f"⛔ Bloqueado por política: Se detectó contenido sensible ({cat}).")
        return True

    def _quick_scan(self, text: str, patterns: List[str]) -> bool:
        """Simple Regex Check"""
        for pattern in patterns:
            if re.search(pattern, text):
                return True
        return False

    def _semantic_verify(self, text: str, category: str) -> bool:
        """
        Uses Local NLI to determine true intent.
        Returns TRUE if it IS a violation (Real Data).
        Returns FALSE if it is innocent (Discussion/Code/Reference).
        """
        snippet = text[:2000] # First 2k chars usually contain header/context
        
        # Dynamic Candidate Labels based on Category
        if category in ["INVOICE", "FINANCIAL_REPORT"]:
             candidate_labels = [
                "accounting document containing real financial data", # Hit
                "educational text about finance",                   # Miss
                "software code related to billing",                 # Miss
                "general discussion about invoices"                 # Miss
            ]
             hit_label = "real financial data"
             
        elif category in ["PAYSLIP", "DNI", "HR"]:
             candidate_labels = [
                "private employee personal data",                   # Hit
                "public human resources policy document",           # Miss
                "resume or cv template"                             # Miss
            ]
             hit_label = "private employee"
        else:
             # Fallback
             return True
             
        try:
            result = self.classifier(snippet, candidate_labels)
            top_label = result['labels'][0]
            top_score = result['scores'][0]
            
            logger.debug(f"AI Check {category}: {top_label} ({top_score:.2f})")
            
            if hit_label in top_label and top_score > 0.6:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Semantic Verify Failed: {e}")
            return True # Fail Safe -> Block if AI fails

    async def _audit_block(self, tenant_id, policy_id, user_id, filename, category, reason):
        try:
            event_data = {
                "tenant_id": tenant_id,
                "policy_id": policy_id,
                "event_type": "FILE_UPLOAD_ATTEMPT",
                "action_taken": "BLOCKED",
                "user_id": user_id,
                "metadata": {
                    "filename": filename,
                    "detected_category": category,
                    "reason": reason, 
                    "method": "SMART_SEMANTIC_GUARD"
                },
                "created_at": "now()"
            }
            supabase.table("policy_events").insert(event_data).execute()
        except:
             pass

file_guardian = FileGuardian()
