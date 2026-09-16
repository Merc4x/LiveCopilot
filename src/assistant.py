"""
LiveCopilot - Real-Time Conversational Assistance Engine (LLM)
Generates instant conversational response suggestions and key talking points using
Groq (Llama-3.3-70b / Qwen) or Google Gemini (Gemini-2.5-Flash / 1.5-Flash).
"""

import collections
import logging
import os
import time
from typing import Deque, Dict, Optional, Tuple

logger = logging.getLogger("LiveCopilot.Assistant")

SYSTEM_PROMPT = (
    "You are a real-time conversational co-pilot for video calls, English interviews, and meetings.\n"
    "Your goal is to help the user immediately understand what was said and know how to respond "
    "in natural, fluent English with phonetic pronunciation guidance so they can speak with confidence.\n"
    "Required response structure (strict 4 lines):\n"
    "HEARD_TRANS: <Spanish translation of what the other person just said>\n"
    "RESPONSE: <The exact, natural, concise phrase the user should say in English (1-2 sentences)>\n"
    "PRONUNCIATION: <Approximated phonetic pronunciation guide written for Spanish speakers, with accent marks on stressed syllables for fluent reading, e.g. 'Di ánser is ráis bicós...'>\n"
    "MEANING: <Spanish meaning/translation of the suggested response>\n\n"
    "RULES:\n"
    "- Respond directly with the 4 tags, without introductions, greetings, or extra commentary.\n"
    "- PRONUNCIATION must be intuitive for Spanish speakers (e.g., using 'u' for 'w', 'di' for 'the', accents on tonic syllables)."
)


class LiveAssistant:
    """
    Conversational co-pilot with a sliding context window and ultra-low latency.
    """

    def __init__(
        self,
        provider: str = "groq",
        groq_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        max_history_turns: int = 4,
    ):
        """
        :param provider: 'groq' or 'gemini'.
        :param groq_api_key: API Key for Groq.
        :param gemini_api_key: API Key for Google Gemini.
        :param max_history_turns: Number of recent conversational turns retained in memory.
        """
        self.provider = provider.lower().strip()
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "").strip()

        # Short-term contextual memory
        self.history: Deque[Dict[str, str]] = collections.deque(maxlen=max_history_turns * 2)

        # Clients
        self.groq_client = None
        self.gemini_client = None

        self._init_providers()

    def _init_providers(self):
        """Initialize AI clients based on available credentials."""
        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key, timeout=3.5)
                logger.info("Groq LLM client initialized successfully.")
            except Exception as e:
                logger.warning("Failed to initialize Groq LLM client: %s", e)

        if self.gemini_api_key:
            try:
                # Support for google-genai or google-generativeai SDKs
                try:
                    from google import genai
                    self.gemini_client = genai.Client(api_key=self.gemini_api_key)
                    self._gemini_type = "google-genai"
                except ImportError:
                    import google.generativeai as gai
                    gai.configure(api_key=self.gemini_api_key)
                    self.gemini_client = gai.GenerativeModel(
                        model_name="gemini-1.5-flash",
                        system_instruction=SYSTEM_PROMPT,
                    )
                    self._gemini_type = "generativeai"
                logger.info("Gemini LLM client initialized successfully (%s).", self._gemini_type)
            except Exception as e:
                logger.warning("Failed to initialize Gemini client: %s", e)

    def _generate_groq(self, prompt_text: str) -> str:
        """Inference using Groq LLMs with automatic model failover."""
        if not self.groq_client:
            raise RuntimeError("Groq client not available.")

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in self.history:
            messages.append(item)
        messages.append({"role": "user", "content": f"The other speaker said: \"{prompt_text}\""})

        # Candidate models ordered by speed, capability, and availability
        candidate_models = [
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
            "groq/compound-mini",
        ]

        # Prioritize previously validated working model in this session
        if hasattr(self, "_preferred_groq_model") and self._preferred_groq_model:
            candidate_models.insert(0, self._preferred_groq_model)

        last_error = None
        for model_name in candidate_models:
            try:
                response = self.groq_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    max_tokens=150,
                    temperature=0.3,
                )
                self._preferred_groq_model = model_name
                return response.choices[0].message.content.strip()
            except Exception as e:
                last_error = e
                logger.debug("Groq model %s unavailable or rate-limited: %s", model_name, e)
                continue

        if last_error:
            raise last_error
        return ""

    def _generate_gemini(self, prompt_text: str) -> str:
        """Inference using Google Gemini Flash."""
        if not self.gemini_client:
            raise RuntimeError("Gemini client not available.")

        full_prompt = (
            f"Recent conversation context:\n"
            + "\n".join([f"{item['role']}: {item['content']}" for item in self.history])
            + f"\n\nWhat was just said: \"{prompt_text}\"\n"
            f"Your concise suggested response (1-2 direct sentences):"
        )

        if self._gemini_type == "google-genai":
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt,
                config={"system_instruction": SYSTEM_PROMPT, "max_output_tokens": 100},
            )
            return response.text.strip()
        else:
            response = self.gemini_client.generate_content(full_prompt)
            return response.text.strip()

    def get_suggestion(self, heard_text: str) -> Tuple[Dict[str, str], float, str]:
        """
        Generate an immediate conversational suggestion for the transcribed speech.
        :param heard_text: Transcription of what the other person said.
        :return: Tuple (parsed_data, latency_ms, provider_used)
        """
        if not heard_text or len(heard_text.strip()) < 3:
            return {}, 0.0, ""

        t_start = time.perf_counter()
        suggestion = ""
        provider_used = "None"

        # Primary provider selection with automatic failover
        if self.provider == "gemini" and self.gemini_client:
            try:
                suggestion = self._generate_gemini(heard_text)
                provider_used = "Gemini Flash"
            except Exception as e:
                logger.warning("Gemini LLM request failed: %s. Falling back to Groq...", e)
                if self.groq_client:
                    try:
                        suggestion = self._generate_groq(heard_text)
                        provider_used = "Groq Llama-3.3 (Fallback)"
                    except Exception as err2:
                        logger.error("Both LLM providers failed: %s", err2)
        else:
            # Default or provider == "groq"
            if self.groq_client:
                try:
                    suggestion = self._generate_groq(heard_text)
                    provider_used = "Groq Llama-3.3"
                except Exception as e:
                    logger.warning("Groq LLM request failed: %s. Falling back to Gemini...", e)
                    if self.gemini_client:
                        try:
                            suggestion = self._generate_gemini(heard_text)
                            provider_used = "Gemini Flash (Fallback)"
                        except Exception as err2:
                            logger.error("Both LLM providers failed: %s", err2)
            elif self.gemini_client:
                try:
                    suggestion = self._generate_gemini(heard_text)
                    provider_used = "Gemini Flash"
                except Exception as e:
                    logger.error("Gemini LLM error: %s", e)

        # Update conversation context
        if suggestion:
            self.history.append({"role": "user", "content": heard_text})
            self.history.append({"role": "assistant", "content": suggestion})

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        parsed_data = self.parse_structured_suggestion(suggestion)
        return parsed_data, latency_ms, provider_used

    @staticmethod
    def parse_structured_suggestion(raw_text: str) -> Dict[str, str]:
        """
        Extract the 4 structured blocks:
        - Translation of heard speech
        - Suggested English response
        - Phonetic pronunciation guide
        - Meaning of response
        """
        parsed = {
            "heard_trans": "",
            "response": "",
            "pronunciation": "",
            "meaning": "",
            # Backward-compatibility aliases
            "trad_escuchado": "",
            "respuesta": "",
            "pronunciacion": "",
            "trad_respuesta": "",
            "raw": raw_text,
        }
        for line in raw_text.splitlines():
            line_str = line.strip()
            upper = line_str.upper()
            if upper.startswith("HEARD_TRANS:") or upper.startswith("TRAD_ESCUCHADO:"):
                val = line_str.split(":", 1)[1].strip()
                parsed["heard_trans"] = val
                parsed["trad_escuchado"] = val
            elif upper.startswith("RESPONSE:") or upper.startswith("RESPUESTA:"):
                val = line_str.split(":", 1)[1].strip()
                parsed["response"] = val
                parsed["respuesta"] = val
            elif upper.startswith("PRONUNCIATION:") or upper.startswith("PRONUNCIACION:"):
                val = line_str.split(":", 1)[1].strip()
                parsed["pronunciation"] = val
                parsed["pronunciacion"] = val
            elif upper.startswith("MEANING:") or upper.startswith("TRAD_RESPUESTA:"):
                val = line_str.split(":", 1)[1].strip()
                parsed["meaning"] = val
                parsed["trad_respuesta"] = val

        if not parsed["response"]:
            parsed["response"] = raw_text
            parsed["respuesta"] = raw_text

        return parsed

    def clear_history(self):
        """Clear conversation history and context buffer."""
        self.history.clear()
        logger.info("Conversational assistant history reset.")
