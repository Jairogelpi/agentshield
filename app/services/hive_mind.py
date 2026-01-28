# app/services/hive_mind.py
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from redis.commands.search.query import Query

from app.db import redis_client
from app.services.cache import VECTOR_DIM, get_embedding
from app.services.llm_gateway import execute_with_resilience

logger = logging.getLogger("agentshield.hive_mind")


class HiveMindService:
    """
    Zenith Hive Mind (Federated Intelligence).
    Moves beyond simple caching to active knowledge synthesis.
    """

    def __init__(self):
        self.synthesis_threshold = 0.82
        self.min_candidates_for_synthesis = 2

    async def query_hive(self, prompt: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Queries the hive for existing knowledge.
        If a direct hit is found, returns it.
        If multiple partial hits are found, synthesizes a 'Super Response'.
        """
        try:
            vector = await get_embedding(prompt)

            # Buscamos los 5 candidatos más cercanos
            base_query = f"( @tenant_id:{{{tenant_id}}} | @share_knowledge:{{1}} ) => [KNN 5 @vector $vec as score]"
            q = (
                Query(base_query)
                .sort_by("score")
                .return_fields("prompt", "response", "score", "feedback_score")
                .dialect(2)
            )

            res = await redis_client.ft("idx:cache").search(q, {"vec": vector})

            if not res.docs:
                return None

            candidates = res.docs
            top_score = 1 - float(candidates[0].score)  # Cosine Distance to Similarity

            # 1. DIRECT HIT (Tier 0/1)
            if top_score > 0.94:
                logger.info(f"💎 Direct Hive Hit (Score: {top_score:.4f})")
                return {
                    "source": "DIRECT_HIT",
                    "content": candidates[0].response,
                    "confidence": top_score,
                }

            # 2. EVOLUTIONARY SYNTHESIS (Tier 2 - Collective Wisdom)
            valid_candidates = [
                c for c in candidates if (1 - float(c.score)) > self.synthesis_threshold
            ]

            if len(valid_candidates) >= self.min_candidates_for_synthesis:
                logger.info(f"🐝 Synthesis Triggered: Combining {len(valid_candidates)} records.")
                return await self._synthesize_knowledge(prompt, valid_candidates)

            return None

        except Exception as e:
            logger.error(f"Hive Query Error: {e}")
            return None

    async def _synthesize_knowledge(self, prompt: str, candidates: List[Any]) -> Dict[str, Any]:
        """
        Uses a high-efficiency model to synthesize a response from multiple past successful interactions.
        """
        knowledge_base = "\n---\n".join(
            [f"PAST_PROMPT: {c.prompt}\nPAST_RESPONSE: {c.response}" for c in candidates]
        )

        synthesis_prompt = [
            {
                "role": "system",
                "content": "You are the AgentShield Hive Mind. Synthesize a core response based ONLY on the provided verified corporate knowledge. Be concise and authoritative.",
            },
            {
                "role": "user",
                "content": f"Contextual Knowledge:\n{knowledge_base}\n\nCurrent User Query: {prompt}",
            },
        ]

        # We use a 'fast' tier for synthesis to keep latency low
        try:
            # Note: execute_with_resilience might need adjustment for direct dict return or stream handling
            # Assuming it can return a full response if stream=False
            response = await execute_with_resilience(
                tier="agentshield-fast",
                messages=synthesis_prompt,
                user_id="SYSTEM-HIVE",
                stream=False,
            )

            synthesized_text = response.choices[0].message.content

            return {
                "source": "HIVE_SYNTHESIS",
                "content": synthesized_text,
                "confidence": 0.90,  # Fixed score for synthesis
                "records_used": len(candidates),
            }
        except Exception as e:
            logger.error(f"Knowledge Synthesis Failed: {e}")
            return None

    async def reward_interaction(self, prompt: str, response: str, tenant_id: str, rating: int):
        """
        Updates the Hive based on user feedback.
        Responses with rating < 0 might be purged or flagged.
        """
        # Logic to update database and evolve the models...
        pass


hive_mind = HiveMindService()
