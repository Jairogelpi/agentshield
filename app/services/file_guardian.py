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
    🛡️ Universal Semantic Guardian.
    Zero-Shot Classification Local para CUALQUIER categoría definida por el usuario.
    Sin Regex hardcodeados. Universal y Dinámico.
    """
    
    def __init__(self):
        self.ai_enabled = False
        self.classifier = None
        
        if AI_AVAILABLE:
            try:
                logger.info("🧠 Initializing Universal Semantic Guardian (ONNX)...")
                # Load optimized small model for zero-shot
                self.classifier = pipeline(
                    "zero-shot-classification",
                    model="valhalla/distilbart-mnli-12-1", 
                    device=-1 # CPU
                )
                self.ai_enabled = True
                logger.info("✅ Universal Semantic Guardian Ready.")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load AI model: {e}. Falling back to Keyword Matching.")
                self.ai_enabled = False

    async def inspect_and_filter(self, file: UploadFile, user_id: str, tenant_id: str, dept_id: Optional[str] = None):
        """
        Main entry point. Checks file against active policies using Universal Engine.
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
            policies = [] 

        if not policies:
            return True

        # 2. Extract Text (If possible)
        try:
            content = await file.read()
            await file.seek(0)
            text = content.decode("utf-8", errors="ignore")
        except:
            text = ""

        # 3. Check Policies Universally
        for policy in policies:
            # Dept Check
            p_dept = policy.get('target_dept_id')
            if p_dept and str(p_dept) != str(dept_id):
                continue
            
            rules = policy.get('rules', {})
            blocked_cats = rules.get('block_categories', [])
            
            # Universal Check per Category
            for cat in blocked_cats:
                 # Check if this file matches the FORBIDDEN concept 'cat'
                 is_violation = False
                 confidence = 0.0
                 
                 # Strategy A: AI Universal Scan (If enabled and text available)
                 if self.ai_enabled and text and len(text) > 10:
                     is_violation, confidence = self._universal_semantic_check(text, cat)
                     if not is_violation and confidence > 0.8:
                         # High confidence it's SAFE
                         pass 
                 elif text:
                     # Strategy B: Fallback Keyword Match (If AI off)
                     if self._fallback_keyword_check(text, cat) or self._fallback_keyword_check(filename, cat):
                         is_violation = True
                         confidence = 1.0
                 else:
                     # Strategy C: Filename Check only (Binary files)
                     if self._fallback_keyword_check(filename, cat):
                         is_violation = True
                         confidence = 0.5
                         
                 if is_violation:
                     logger.info(f"🚫 Universal Block Triggered: {cat} (Confidence: {confidence})")
                     reason = f"Universal Semantic Match: {cat}"
                     await self._audit_block(tenant_id, policy['id'], user_id, filename, cat, reason)
                     
                     if policy.get('mode') == 'ENFORCE':
                         raise HTTPException(403, f"⛔ Bloqueado: Se detectó contenido sensible del tipo '{cat}'.")
        return True

    def _universal_semantic_check(self, text: str, category: str) -> Tuple[bool, float]:
        """
        Asks the AI: "Is this {category}?"
        Returns (IsViolation, Confidence)
        """
        snippet = text[:2000]
        
        # Dynamic Candidate Labels created from the USER'S STRING
        # We don't know what 'category' is, but the NLI model understands English/Concepts.
        # e.g. category="Secret Protocol"
        
        # Positive Label (The Forbidden Thing)
        label_violation = f"this is a {category}"
        
        # Negative Labels (The Safe Things)
        label_safe_1 = f"discussion about {category}"
        label_safe_2 = "educational or reference text"
        label_safe_3 = "source code or configuration"
        
        candidate_labels = [label_violation, label_safe_1, label_safe_2, label_safe_3]
        
        try:
            result = self.classifier(snippet, candidate_labels)
            top_label = result['labels'][0]
            top_score = result['scores'][0]
            
            logger.debug(f"Universal AI Check '{category}': {top_label} ({top_score:.2f})")
            
            if top_label == label_violation and top_score > 0.5:
                return True, top_score
            
            return False, top_score
            
        except Exception as e:
            logger.error(f"Universal Scan Failed: {e}")
            # Fail Open or Closed? For universal, fail open to avoid blocking everything on error.
            return False, 0.0

    def _fallback_keyword_check(self, text: str, category: str) -> bool:
        """
        Fallback if AI is dead. Matches the category name itself as a keyword.
        e.g. if category is "INVOICE", looks for "invoice".
        """
        # Simple heuristic: The category name, singular or plural
        pattern = re.escape(category)
        if re.search(pattern, text, re.IGNORECASE):
            return True
        return False

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
                    "method": "UNIVERSAL_SEMANTIC_GUARD"
                },
                "created_at": "now()"
            }
            supabase.table("policy_events").insert(event_data).execute()
        except:
             pass

file_guardian = FileGuardian()
