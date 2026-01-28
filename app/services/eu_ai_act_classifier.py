# app/services/eu_ai_act_classifier.py
"""
EU AI Act Risk Classification Engine (Revolutionary 2026).
Automatic classification of AI system usage according to EU AI Act Articles 5-7.
"""
import logging
import re
from typing import Dict, Tuple
from enum import Enum

from litellm import completion

logger = logging.getLogger("agentshield.eu_ai_act")


class RiskLevel(str, Enum):
    """EU AI Act Risk Levels (Articles 6-7)"""
    PROHIBITED = "PROHIBITED"  # Article 5 - Immediate block
    HIGH_RISK = "HIGH_RISK"    # Annex III - Human oversight required
    LIMITED_RISK = "LIMITED_RISK"  # Article 52 - Transparency required
    MINIMAL_RISK = "MINIMAL_RISK"  # No special requirements


class RiskCategory(str, Enum):
    """High-Risk Categories (Annex III)"""
    # Prohibited uses
    SOCIAL_SCORING = "SOCIAL_SCORING"
    BIOMETRIC_SURVEILLANCE = "BIOMETRIC_SURVEILLANCE"
    EMOTION_RECOGNITION = "EMOTION_RECOGNITION"
    MANIPULATION = "MANIPULATION"
    
    # High-risk uses
    HR_RECRUITMENT = "HR_RECRUITMENT"
    HR_PERFORMANCE = "HR_PERFORMANCE"
    EDUCATION_ASSESSMENT = "EDUCATION_ASSESSMENT"
    EDUCATION_ADMISSION = "EDUCATION_ADMISSION"
    CREDIT_SCORING = "CREDIT_SCORING"
    INSURANCE_PRICING = "INSURANCE_PRICING"
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    MEDICAL_DIAGNOSIS = "MEDICAL_DIAGNOSIS"
    CRITICAL_INFRASTRUCTURE = "CRITICAL_INFRASTRUCTURE"
    
    # Limited risk
    CHATBOT = "CHATBOT"
    CONTENT_GENERATION = "CONTENT_GENERATION"
    DEEPFAKE = "DEEPFAKE"
    
    # Minimal risk
    GENERAL_PURPOSE = "GENERAL_PURPOSE"


class EUAIActClassifier:
    """
    Revolutionary EU AI Act Compliance Classifier (2026).
    Automatically classifies requests according to EU AI Act risk levels.
    """
    
    def __init__(self):
        # Article 5: Prohibited Practices
        self.prohibited_patterns = {
            RiskCategory.SOCIAL_SCORING: [
                r"(?i)(social\s+credit|social\s+score|trustworthiness\s+score)",
                r"(?i)(citizen\s+rating|behavior\s+score|reputation\s+system)",
                r"(?i)(rank\s+people|evaluate\s+individuals|score\s+citizens)"
            ],
            RiskCategory.BIOMETRIC_SURVEILLANCE: [
                r"(?i)(real-?time\s+face\s+recognition|live\s+facial\s+recognition)",
                r"(?i)(public\s+surveillance|mass\s+surveillance|biometric\s+identification)",
                r"(?i)(track\s+people|identify\s+individuals\s+in\s+public)"
            ],
            RiskCategory.EMOTION_RECOGNITION: [
                r"(?i)(detect\s+emotion|emotion\s+recognition|sentiment\s+detection)",
                r"(?i)(workplace\s+mood|employee\s+emotion|student\s+feeling)",
                r"(?i)(emotional\s+state\s+in\s+(workplace|school|education))"
            ],
            RiskCategory.MANIPULATION: [
                r"(?i)(subliminal\s+technique|manipulate\s+behavior|exploit\s+vulnerabilit)",
                r"(?i)(influence\s+decision|persuade\s+without\s+awareness)",
                r"(?i)(hidden\s+message|subconscious\s+influence)"
            ]
        }
        
        # Annex III: High-Risk Categories
        self.high_risk_patterns = {
            RiskCategory.HR_RECRUITMENT: [
                r"(?i)(recruit|hire|candidate\s+selection|job\s+applicant)",
                r"(?i)(cv\s+screening|resume\s+analysis|talent\s+acquisition)",
                r"(?i)(interview\s+evaluation|hiring\s+decision)"
            ],
            RiskCategory.HR_PERFORMANCE: [
                r"(?i)(performance\s+review|employee\s+evaluation|promotion\s+decision)",
                r"(?i)(productivity\s+analysis|termination\s+decision|dismiss)"
            ],
            RiskCategory.EDUCATION_ASSESSMENT: [
                r"(?i)(student\s+grade|exam\s+scoring|academic\s+evaluation)",
                r"(?i)(test\s+assessment|learning\s+evaluation)"
            ],
            RiskCategory.EDUCATION_ADMISSION: [
                r"(?i)(student\s+admission|university\s+acceptance|school\s+selection)",
                r"(?i)(enroll(ment)?\s+decision|admission\s+criteria)"
            ],
            RiskCategory.CREDIT_SCORING: [
                r"(?i)(credit\s+score|creditworthiness|loan\s+approval)",
                r"(?i)(financial\s+risk|default\s+probability|lending\s+decision)"
            ],
            RiskCategory.MEDICAL_DIAGNOSIS: [
                r"(?i)(diagnos(is|e)|medical\s+condition|disease\s+detection)",
                r"(?i)(patient\s+assessment|clinical\s+decision|treatment\s+recommendation)"
            ],
            RiskCategory.LAW_ENFORCEMENT: [
                r"(?i)(crime\s+prediction|recidivism|risk\s+assessment\s+in\s+law)",
                r"(?i)(suspect\s+identification|criminal\s+profiling)"
            ]
        }
        
        # Article 52: Limited Risk (Transparency Required)
        self.limited_risk_patterns = {
            RiskCategory.CHATBOT: [
                r"(?i)(chat|conversation|dialogue|interact\s+with\s+user)",
                r"(?i)(virtual\s+assistant|ai\s+agent|bot)"
            ],
            RiskCategory.CONTENT_GENERATION: [
                r"(?i)(generate\s+content|create\s+(text|image|video|audio))",
                r"(?i)(synthetic\s+media|ai-generated)"
            ],
            RiskCategory.DEEPFAKE: [
                r"(?i)(deepfake|face\s+swap|voice\s+clone|synthetic\s+person)",
                r"(?i)(manipulate\s+(video|image|audio))"
            ]
        }
    
    def classify(self, prompt: str, context: Dict = None) -> Tuple[RiskLevel, RiskCategory, float]:
        """
        Classify a request according to EU AI Act.
        
        Args:
            prompt: User's prompt/request
            context: Additional context (department, use_case, etc.)
        
        Returns:
            (risk_level, risk_category, confidence)
        """
        context = context or {}
        
        # LAYER 1: Pattern-based detection (fast, high precision)
        risk_level, category, confidence = self._pattern_based_classification(prompt, context)
        
        if confidence >= 0.9:
            logger.info(f"✅ EU AI Act Classification: {risk_level} - {category} (confidence: {confidence})")
            return risk_level, category, confidence
        
        # LAYER 2: LLM-based classification (slower, higher recall)
        llm_risk, llm_category, llm_confidence = self._llm_based_classification(prompt, context)
        
        # Combine results (take most restrictive)
        final_risk = self._most_restrictive(risk_level, llm_risk)
        final_category = category if confidence > llm_confidence else llm_category
        final_confidence = max(confidence, llm_confidence)
        
        logger.info(f"🔍 EU AI Act Classification: {final_risk} - {final_category} (confidence: {final_confidence})")
        
        return final_risk, final_category, final_confidence
    
    def _pattern_based_classification(self, prompt: str, context: Dict) -> Tuple[RiskLevel, RiskCategory, float]:
        """Fast pattern-based classification."""
        # Check PROHIBITED first (Article 5)
        for category, patterns in self.prohibited_patterns.items():
            for pattern in patterns:
                if re.search(pattern, prompt):
                    return RiskLevel.PROHIBITED, category, 0.95
        
        # Check HIGH_RISK (Annex III)
        for category, patterns in self.high_risk_patterns.items():
            for pattern in patterns:
                if re.search(pattern, prompt):
                    return RiskLevel.HIGH_RISK, category, 0.90
        
        # Check LIMITED_RISK (Article 52)
        for category, patterns in self.limited_risk_patterns.items():
            for pattern in patterns:
                if re.search(pattern, prompt):
                    return RiskLevel.LIMITED_RISK, category, 0.85
        
        # Default: MINIMAL_RISK
        return RiskLevel.MINIMAL_RISK, RiskCategory.GENERAL_PURPOSE, 0.50
    
    def _llm_based_classification(self, prompt: str, context: Dict) -> Tuple[RiskLevel, RiskCategory, float]:
        """LLM-based classification for edge cases."""
        try:
            system_prompt = """You are an EU AI Act compliance expert. Classify the AI system usage into risk levels:

PROHIBITED (Article 5): Social scoring, real-time biometric surveillance, emotion recognition in workplace/education, manipulation
HIGH_RISK (Annex III): HR, Education, Credit, Medical, Law enforcement, Critical infrastructure
LIMITED_RISK (Article 52): Chatbots, content generation, deepfakes (requires transparency)
MINIMAL_RISK: General purpose tools

Return JSON: {"risk_level": "...", "category": "...", "confidence": 0.95, "reasoning": "..."}"""
            
            response = completion(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Classify this request:\n\n{prompt}\n\nContext: {context}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            
            risk_level = RiskLevel(result["risk_level"])
            category = RiskCategory(result.get("category", "GENERAL_PURPOSE"))
            confidence = result.get("confidence", 0.7)
            
            logger.info(f"🤖 LLM Classification: {result.get('reasoning', 'N/A')}")
            
            return risk_level, category, confidence
            
        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")
            return RiskLevel.MINIMAL_RISK, RiskCategory.GENERAL_PURPOSE, 0.3
    
    def _most_restrictive(self, level1: RiskLevel, level2: RiskLevel) -> RiskLevel:
        """Return the most restrictive risk level."""
        order = [RiskLevel.MINIMAL_RISK, RiskLevel.LIMITED_RISK, RiskLevel.HIGH_RISK, RiskLevel.PROHIBITED]
        return level1 if order.index(level1) > order.index(level2) else level2


# Global instance
eu_ai_act_classifier = EUAIActClassifier()
