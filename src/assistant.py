"""
LiveCopilot - Motor de Asistencia Conversacional en Tiempo Real (LLM)
Genera sugerencias inmediatas de respuesta y puntos clave utilizando
Groq (Llama-3.3-70b / Llama-3.1-8b) o Google Gemini (Gemini-2.5-Flash).
"""

import collections
import logging
import os
import time
from typing import Deque, Dict, Optional, Tuple

logger = logging.getLogger("LiveCopilot.Assistant")

SYSTEM_PROMPT = (
    "Eres un copiloto conversacional en tiempo real para videollamadas, clases de inglés y reuniones.\n"
    "Tu objetivo es que el usuario comprenda inmediatamente lo que acaban de decir y sepa qué responder "
    "en inglés con la pronunciación fonética exacta para hablar con seguridad.\n"
    "Estructura obligatoria de respuesta (4 líneas estrictas):\n"
    "TRAD_ESCUCHADO: <Traducción al español de lo que dijo la otra persona>\n"
    "RESPUESTA: <La frase exacta, natural y concisa que el usuario debe decir en inglés (1-2 oraciones)>\n"
    "PRONUNCIACION: <Guía fonética aproximada en español con tildes en la sílaba acentuada para leer fluido, ej: 'Di ánser is ráis bicós...'>\n"
    "TRAD_RESPUESTA: <Significado en español de la respuesta>\n\n"
    "REGLAS:\n"
    "- Responde directamente con las 4 etiquetas, sin saludos ni preámbulos.\n"
    "- La PRONUNCIACION debe escribirse con fonética intuitiva para hispanohablantes (usando 'u' para w, 'di' para the, tildes en sílabas tónicas)."
)


class LiveAssistant:
    """
    Copiloto conversacional con ventana de contexto deslizante y latencia ultra-baja.
    """

    def __init__(
        self,
        provider: str = "groq",
        groq_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        max_history_turns: int = 4,
    ):
        """
        :param provider: 'groq' o 'gemini'.
        :param groq_api_key: API Key para Groq.
        :param gemini_api_key: API Key para Google Gemini.
        :param max_history_turns: Cantidad de intercambios recientes en memoria.
        """
        self.provider = provider.lower().strip()
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "").strip()

        # Memoria contextual corta
        self.history: Deque[Dict[str, str]] = collections.deque(maxlen=max_history_turns * 2)

        # Clientes
        self.groq_client = None
        self.gemini_client = None

        self._init_providers()

    def _init_providers(self):
        """Inicializa los clientes de IA según las credenciales disponibles."""
        if self.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.groq_api_key, timeout=3.5)
                logger.info("Cliente Groq LLM preparado.")
            except Exception as e:
                logger.warning("Fallo al inicializar Groq LLM: %s", e)

        if self.gemini_api_key:
            try:
                # Soporte para la nueva SDK google-genai o google-generativeai
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
                logger.info("Cliente Gemini inicializado exitosamente (%s).", self._gemini_type)
            except Exception as e:
                logger.warning("Fallo al inicializar Gemini: %s", e)

    def _generate_groq(self, prompt_text: str) -> str:
        """Inferencia con Groq LLM (Qwen, GPT-OSS, Llama) con failover automático de modelos."""
        if not self.groq_client:
            raise RuntimeError("Cliente Groq no disponible.")

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in self.history:
            messages.append(item)
        messages.append({"role": "user", "content": f"El interlocutor dijo: \"{prompt_text}\""})

        # Modelos candidatos en orden de calidad y disponibilidad
        candidate_models = [
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
            "groq/compound-mini",
        ]

        # Si ya descubrimos un modelo que funciona en esta sesión, priorizarlo
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
                logger.debug("Modelo Groq %s no disponible o con límite: %s", model_name, e)
                continue

        if last_error:
            raise last_error
        return ""

    def _generate_gemini(self, prompt_text: str) -> str:
        """Inferencia con Google Gemini Flash."""
        if not self.gemini_client:
            raise RuntimeError("Cliente Gemini no disponible.")

        full_prompt = (
            f"Contexto reciente de la conversación:\n"
            + "\n".join([f"{item['role']}: {item['content']}" for item in self.history])
            + f"\n\nLo que acaban de decir: \"{prompt_text}\"\n"
            f"Tu sugerencia concisa (1-2 oraciones directas):"
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

    def get_suggestion(self, heard_text: str) -> Tuple[str, float, str]:
        """
        Genera una sugerencia conversacional inmediata para el texto escuchado.
        :param heard_text: Transcripción de lo que dijo la otra persona.
        :return: Tuple (sugerencia, latencia_ms, proveedor_usado)
        """
        if not heard_text or len(heard_text.strip()) < 3:
            return "", 0.0, ""

        t_start = time.perf_counter()
        suggestion = ""
        provider_used = "Ninguno"

        # Decisión del proveedor primario con failover
        if self.provider == "gemini" and self.gemini_client:
            try:
                suggestion = self._generate_gemini(heard_text)
                provider_used = "Gemini Flash"
            except Exception as e:
                logger.warning("Fallo Gemini LLM: %s. Reintentando con Groq...", e)
                if self.groq_client:
                    try:
                        suggestion = self._generate_groq(heard_text)
                        provider_used = "Groq Llama-3.3 (Fallback)"
                    except Exception as err2:
                        logger.error("Ambos proveedores LLM fallaron: %s", err2)
        else:
            # Por defecto o si provider == "groq"
            if self.groq_client:
                try:
                    suggestion = self._generate_groq(heard_text)
                    provider_used = "Groq Llama-3.3"
                except Exception as e:
                    logger.warning("Fallo Groq LLM: %s. Reintentando con Gemini...", e)
                    if self.gemini_client:
                        try:
                            suggestion = self._generate_gemini(heard_text)
                            provider_used = "Gemini Flash (Fallback)"
                        except Exception as err2:
                            logger.error("Ambos proveedores LLM fallaron: %s", err2)
            elif self.gemini_client:
                try:
                    suggestion = self._generate_gemini(heard_text)
                    provider_used = "Gemini Flash"
                except Exception as e:
                    logger.error("Fallo Gemini LLM: %s", e)

        # Actualizar memoria de conversación
        if suggestion:
            self.history.append({"role": "user", "content": heard_text})
            self.history.append({"role": "assistant", "content": suggestion})

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        parsed_data = self.parse_structured_suggestion(suggestion)
        return parsed_data, latency_ms, provider_used

    @staticmethod
    def parse_structured_suggestion(raw_text: str) -> Dict[str, str]:
        """Extrae los 4 bloques: traducción de lo escuchado, respuesta en inglés, fonética y significado."""
        parsed = {
            "trad_escuchado": "",
            "respuesta": "",
            "pronunciacion": "",
            "trad_respuesta": "",
            "raw": raw_text,
        }
        for line in raw_text.splitlines():
            line_str = line.strip()
            if line_str.upper().startswith("TRAD_ESCUCHADO:"):
                parsed["trad_escuchado"] = line_str[len("TRAD_ESCUCHADO:"):].strip()
            elif line_str.upper().startswith("RESPUESTA:"):
                parsed["respuesta"] = line_str[len("RESPUESTA:"):].strip()
            elif line_str.upper().startswith("PRONUNCIACION:"):
                parsed["pronunciacion"] = line_str[len("PRONUNCIACION:"):].strip()
            elif line_str.upper().startswith("TRAD_RESPUESTA:"):
                parsed["trad_respuesta"] = line_str[len("TRAD_RESPUESTA:"):].strip()

        if not parsed["respuesta"]:
            parsed["respuesta"] = raw_text
        return parsed

    def clear_history(self):
        """Limpia el contexto histórico acumulado."""
        self.history.clear()
        logger.info("Historial conversacional del asistente reiniciado.")
