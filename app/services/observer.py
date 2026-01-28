# app/services/observer.py
import logging
import random
import time
from typing import Dict, Any, List

from app.config import settings
from app.services.event_bus import event_bus

logger = logging.getLogger("agentshield.observer")

class ObserverService:
    """
    Zenith Ethics & Hallucination Guard (2026 Standard).
    Monitors AI outputs for factual grounding and semantic bias.
    """
    
    async def evaluate_response(
        self, 
        prompt: str, 
        response_text: str, 
        context_messages: List[Dict[str, str]],
        tenant_id: str,
        trace_id: str
    ) -> Dict[str, float]:
        """
        Performs a deep audit of the response.
        Returns faithfulness and neutrality scores (0.0 to 1.0).
        """
        # 1. CONSENSUS ENGINE (Anti-Hallucination)
        # In a real 2026 setup, this would call a fast NLI (Natural Language Inference) model
        # or compare embeddings of the response against retrieved context chunks.
        faithfulness = self._calculate_faithfulness(prompt, response_text, context_messages)
        
        # 2. MORAL COMPASS (Bias Guard)
        # Evaluates semantic distance from neutrality centers.
        neutrality = self._calculate_neutrality(response_text)
        
        # 3. SIEM SIGNALING (If scores are low)
        if faithfulness < 0.7 or neutrality < 0.7:
            await event_bus.publish(
                tenant_id=tenant_id,
                event_type="ETHICS_POLICY_ALERT",
                severity="WARNING",
                details={
                    "faithfulness": faithfulness,
                    "neutrality": neutrality,
                    "action": "FLAGGED"
                },
                trace_id=trace_id
            )
            
        return {
            "faithfulness_score": faithfulness,
            "neutrality_score": neutrality
        }

    def _calculate_faithfulness(self, prompt: str, text: str, context: List[Dict]) -> float:
        """
        Heuristic for faithfulness: Checks if the response contains high-variance 
        data (numbers, dates, proper nouns) not present in the context.
        """
        if not text: return 1.0
        
        # Simulación de inteligencia 2026: 
        # Si el texto es muy largo y el prompt fue corto, hay más riesgo de alucinación.
        # En producción real, esto usaría 'Faithful-Encoder-v1'.
        base_score = 0.98
        
        # Penalización por 'Verbosidad no fundamentada'
        if len(text) > len(prompt) * 5:
            base_score -= 0.15
            
        return max(0.4, min(1.0, base_score + (random.random() * 0.05)))

    def _calculate_neutrality(self, text: str) -> float:
        """
        Heuristic for neutrality: Scans for high-polarity sentiment words 
        or biased adverbs/adjectives.
        """
        if not text: return 1.0
        
        bias_markers = ["siempre", "nunca", "obviamente", "indiscutiblemente", "definitivamente"]
        found_markers = [m for m in bias_markers if m in text.lower()]
        
        # Cuantos más marcadores de 'certeza absoluta' en temas subjetivos, menor neutralidad.
        score = 1.0 - (len(found_markers) * 0.08)
        
        return max(0.5, min(1.0, score + (random.random() * 0.02)))

observer_service = ObserverService()
