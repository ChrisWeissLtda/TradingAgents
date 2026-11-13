"""Token accounting by agent, and prompt caching for the analysts' tool loops."""

import copy
import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from cli.stats_handler import StatsCallbackHandler
from tradingagents import default_config
from tradingagents.agents.analysts.turn import _cache_prefix
from tradingagents.dataflows.config import set_config


@pytest.mark.unit
def test_usage_is_split_by_graph_node():
    h = StatsCallbackHandler()
    for node, (i, o, cr, cw) in {"Market Analyst": (1000, 200, 800, 100), "Trader": (500, 50, 0, 0)}.items():
        run = uuid.uuid4()
        h.on_chat_model_start({}, [[]], run_id=run, metadata={"langgraph_node": node})
        msg = AIMessage(content="x", usage_metadata={"input_tokens": i, "output_tokens": o, "total_tokens": i + o,
                                                     "input_token_details": {"cache_read": cr, "cache_creation": cw}})
        h.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=run)
    by = h.get_stats()["by_node"]
    assert by["Market Analyst"] == {"calls": 1, "input": 1000, "output": 200, "cache_read": 800, "cache_write": 100}
    assert by["Trader"]["input"] == 500
    assert h.get_stats()["tokens_in"] == 1500


class _Fake:
    def __init__(self, llm_type):
        self._llm_type = llm_type

    def bind(self, **kw):
        return ("bound", kw)


@pytest.mark.unit
def test_cache_only_on_the_direct_anthropic_api():
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))
    r = _Fake("anthropic-chat")
    assert _cache_prefix(r, r) == ("bound", {"cache_control": {"type": "ephemeral"}})
    other = _Fake("openai-chat")
    assert _cache_prefix(other, other) is other


@pytest.mark.unit
def test_cache_can_be_switched_off():
    config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    config["anthropic_prompt_cache"] = False
    set_config(config)
    r = _Fake("anthropic-chat")
    assert _cache_prefix(r, r) is r
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))
