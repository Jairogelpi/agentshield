# app/services/llm_pattern_generator.py
"""
LLM-Assisted PII Pattern Generator (Revolutionary 2026).
Uses GPT-5.2 to auto-generate regex patterns from natural language descriptions.
"""
import json
import logging
from typing import Dict, List, Optional

from litellm import completion

logger = logging.getLogger("agentshield.llm_pattern_generator")


class LLMPatternGenerator:
    """
    Revolutionary LLM-Assisted Pattern Generator.
    Converts "contraseñas de empleado" → precise regex pattern.
    """

    def __init__(self, model: str = "gpt-4"):
        self.model = model

    async def generate_pattern(
        self,
        data_type_description: str,
        context: Optional[str] = None,
        language: str = "es"
    ) -> Dict:
        """
        Generate PII detection pattern using LLM.
        
        Args:
            data_type_description: Natural language description (e.g., "contraseñas de empleado")
            context: Additional context about the data
            language: Language for examples
        
        Returns:
            {
                "regex_pattern": str,
                "confidence": float,
                "test_examples": List[str],
                "rationale": str,
                "pattern_type": str
            }
        """
        prompt = self._build_generation_prompt(data_type_description, context, language)
        
        try:
            response = completion(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert in regex patterns for PII detection. Generate precise, production-ready patterns."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3,  # Lower temp for more consistent patterns
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Validate and enhance result
            validated_result = self._validate_and_enhance(result, data_type_description)
            
            logger.info(f"✅ Generated pattern for '{data_type_description}' with confidence {validated_result['confidence']}")
            
            return validated_result
            
        except Exception as e:
            logger.error(f"LLM Pattern Generation Failed: {e}")
            # Fallback: simple generic pattern
            return {
                "regex_pattern": r"(?i)" + data_type_description.replace(" ", "_"),
                "confidence": 0.3,
                "test_examples": [],
                "rationale": "Fallback pattern due to LLM error",
                "pattern_type": "GENERIC",
                "error": str(e)
            }
    
    def _build_generation_prompt(
        self,
        data_type: str,
        context: Optional[str],
        language: str
    ) -> str:
        """Build the LLM prompt for pattern generation."""
        return f"""Generate a precise regex pattern to detect the following sensitive data type.

**Data Type**: {data_type}
**Context**: {context or "General purpose"}
**Language**: {language}

**Requirements**:
1. The regex must be **production-ready** (minimize false positives)
2. Cover **common variations** and formats
3. Be compatible with **Python re module**
4. Consider **internationalization** (if applicable)
5. Be **efficient** (avoid catastrophic backtracking)

**Return a JSON object with**:
{{
  "regex_pattern": "your_pattern_here",
  "confidence": 0.95,
  "test_examples": ["example1", "example2", "example3"],
  "rationale": "Brief explanation of the pattern",
  "pattern_type": "PASSWORD|API_KEY|CUSTOM_ID|ADDRESS|etc."
}}

**Example Output for "employee passwords"**:
{{
  "regex_pattern": "(?i)(employee[_-]?password|emp[_-]?pwd)\\\\s*[:=]\\\\s*[^\\\\s]{{6,}}",
  "confidence": 0.92,
  "test_examples": [
    "employee_password=MySecret123",
    "EMP-PWD: secure_pass"
  ],
  "rationale": "Matches common employee password label patterns with at least 6 chars",
  "pattern_type": "PASSWORD"
}}

Now generate for: "{data_type}"
"""
    
    def _validate_and_enhance(self, result: Dict, original_input: str) -> Dict:
        """Validate and enhance LLM-generated pattern."""
        import re
        
        # Ensure required fields
        if "regex_pattern" not in result:
            raise ValueError("LLM did not return regex_pattern")
        
        # Test pattern validity
        try:
            re.compile(result["regex_pattern"])
        except re.error as e:
            logger.warning(f"Invalid regex from LLM: {e}. Using fallback.")
            result["regex_pattern"] = r"(?i)" + re.escape(original_input)
            result["confidence"] = 0.2
        
        # Ensure confidence is in range
        result["confidence"] = max(0.0, min(1.0, result.get("confidence", 0.5)))
        
        # Ensure test_examples
        if "test_examples" not in result or not result["test_examples"]:
            result["test_examples"] = []
        
        # Add metadata
        result["generated_at"] = "2026-01-28"
        result["llm_model"] = self.model
        
        return result
    
    def test_pattern(self, pattern: str, test_strings: List[str]) -> Dict:
        """
        Test a regex pattern against sample strings.
        
        Returns:
            {
                "matches": List[str],
                "non_matches": List[str],
                "accuracy": float
            }
        """
        import re
        
        matches = []
        non_matches = []
        
        try:
            compiled_pattern = re.compile(pattern)
            for test_str in test_strings:
                if compiled_pattern.search(test_str):
                    matches.append(test_str)
                else:
                    non_matches.append(test_str)
        except re.error as e:
            logger.error(f"Pattern test failed: {e}")
            return {"error": str(e)}
        
        total = len(test_strings)
        accuracy = len(matches) / total if total > 0 else 0.0
        
        return {
            "matches": matches,
            "non_matches": non_matches,
            "accuracy": accuracy,
            "total_tested": total
        }


# Global instance
llm_pattern_generator = LLMPatternGenerator()
