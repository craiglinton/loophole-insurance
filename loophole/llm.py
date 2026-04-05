from __future__ import annotations

import os

from openai import OpenAI


class LLMClient:
    def __init__(
        self,
        model: str = "minimax-m2.7:cloud",
        max_tokens: int = 4096,
    ):
        self.client = OpenAI(
            base_url="https://ollama.com/v1",
            api_key=os.environ.get("OLLAMA_API_KEY", ""),
        )
        self.model = model
        self.max_tokens = max_tokens

    def call(self, system: str, user_message: str, temperature: float = 0.5) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=system,
            input=user_message,
            temperature=temperature,
            max_output_tokens=self.max_tokens,
        )
        return response.output_text
