import json
from typing import Any, Generator

from openai import OpenAI
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.completion_create_params import ResponseFormat
from pydantic import BaseModel

from bpmn_assistant.config import logger
from bpmn_assistant.core.enums import MessageRole, OpenAIModels, OutputMode
from bpmn_assistant.core.llm_provider import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, output_mode: OutputMode = OutputMode.JSON):
        self.output_mode = output_mode
        self.client = OpenAI(api_key=api_key)

    def call(
        self,
        model: str,
        prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        structured_output: BaseModel | None = None,
    ) -> str | dict[str, Any]:
        """
        Implementation of the OpenAI API call.
        """
        messages.append({"role": "user", "content": prompt})

        response_format: ResponseFormat = (
            {"type": "json_object"}
            if self.output_mode == OutputMode.JSON
            else {"type": "text"}
        )

        params = {
            "model": model,
            "response_format": response_format,
            "messages": messages,  # type: ignore[arg-type]
        }

        if model in [OpenAIModels.O1.value, OpenAIModels.O3_MINI.value]:
            logger.info("Using o-series models")
            # https://platform.openai.com/docs/guides/reasoning#limitations
            # constraining the max_completion_tokens can lead to empty responses
        else:
            params["max_tokens"] = max_tokens
            params["temperature"] = temperature

        response = self.client.chat.completions.create(**params)

        raw_output = response.choices[0].message.content

        if raw_output is None:
            raise ValueError("Empty response from OpenAI")

        return self._process_response(raw_output)

    def stream(
        self,
        model: str,
        prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> Generator[str, None, None]:
        """
        Implementation of the OpenAI API stream.
        """
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        for chunk in response:
            if (
                isinstance(chunk, ChatCompletionChunk)
                and chunk.choices[0].delta.content is not None
            ):
                yield chunk.choices[0].delta.content

    def get_initial_messages(self) -> list[dict[str, str]]:
        return (
            [
                {
                    "role": "system",
                    "content": "You are a helpful assistant designed to output JSON.",
                }
            ]
            if self.output_mode == OutputMode.JSON
            else []
        )

    def add_message(
        self, messages: list[dict[str, str]], role: MessageRole, content: str
    ) -> None:
        message_role = "assistant" if role == MessageRole.ASSISTANT else "user"
        messages.append({"role": message_role, "content": content})

    def check_model_compatibility(self, model: str) -> bool:
        return model in [m.value for m in OpenAIModels]

    def _process_response(self, raw_output: str) -> str | dict[str, Any]:
        """
        Process the raw output from the model. Returns the appropriate response based on the output mode.
        If the output mode is JSON, the raw output is parsed and returned as a dict.
        If the output mode is text, the raw output is returned as is.
        """
        if self.output_mode == OutputMode.JSON:
            try:
                result = json.loads(raw_output)

                if not isinstance(result, dict):
                    raise ValueError(f"Invalid JSON response from OpenAI: {result}")

                return result
            except json.decoder.JSONDecodeError as e:
                logger.error(f"JSONDecodeError: {e}")
                logger.error(f"Raw output: {raw_output}")
                raise Exception("Invalid JSON response from OpenAI") from e
        elif self.output_mode == OutputMode.TEXT:
            return raw_output
        else:
            raise ValueError(f"Unsupported output mode: {self.output_mode}")
