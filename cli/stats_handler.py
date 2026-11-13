import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult


class StatsCallbackHandler(BaseCallbackHandler):
    """Callback handler that tracks LLM calls, tool calls, and token usage."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._node_of_run: dict[Any, str] = {}
        # per graph node: calls, input, output, cache_read, cache_write tokens
        self.by_node: dict[str, dict[str, int]] = {}

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when an LLM starts."""
        with self._lock:
            self.llm_calls += 1

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        """Increment LLM call counter when a chat model starts."""
        node = (kwargs.get("metadata") or {}).get("langgraph_node") or "other"
        with self._lock:
            self.llm_calls += 1
            if kwargs.get("run_id") is not None:
                self._node_of_run[kwargs["run_id"]] = node

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Extract token usage from LLM response."""
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return

        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata

        if usage_metadata:
            details = usage_metadata.get("input_token_details") or {}
            with self._lock:
                self.tokens_in += usage_metadata.get("input_tokens", 0)
                self.tokens_out += usage_metadata.get("output_tokens", 0)
                node = self._node_of_run.pop(kwargs.get("run_id"), "other")
                row = self.by_node.setdefault(node, {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
                row["calls"] += 1
                row["input"] += usage_metadata.get("input_tokens", 0)
                row["output"] += usage_metadata.get("output_tokens", 0)
                row["cache_read"] += details.get("cache_read", 0) or 0
                row["cache_write"] += details.get("cache_creation", 0) or 0

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Increment tool call counter when a tool starts."""
        with self._lock:
            self.tool_calls += 1

    def get_stats(self) -> dict[str, Any]:
        """Return current statistics."""
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "by_node": {k: dict(v) for k, v in self.by_node.items()},
            }
