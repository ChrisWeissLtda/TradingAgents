"""The caller's playbook: per-role sections of a markdown file added to the agents' prompts."""

import copy

import pytest

from tradingagents import default_config
from tradingagents.agents.context import get_knowledge_instruction
from tradingagents.dataflows.config import set_config

PLAYBOOK = """# Capri
texto antes da primeira seção é ignorado

## Todos
Separar fato, consenso e opinião.

## Analistas
Checar a conversão de lucro em caixa.

## Decisao
Compras novas saem só do aporte do mês.

## Credito: analistas
Somar o risco sacado à dívida.
"""


@pytest.fixture
def playbook(tmp_path):
    path = tmp_path / "conhecimento.md"
    path.write_text(PLAYBOOK, encoding="utf-8")
    yield path
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))


def _use(path, modes=""):
    config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    config["knowledge_path"] = str(path) if path else None
    config["knowledge_modes"] = modes
    set_config(config)


@pytest.mark.unit
def test_each_role_gets_the_shared_section_and_its_own(playbook):
    _use(playbook)
    analistas = get_knowledge_instruction("analistas")
    decisao = get_knowledge_instruction("decisao")
    assert "fato, consenso e opinião" in analistas and "fato, consenso e opinião" in decisao
    assert "conversão de lucro em caixa" in analistas and "conversão de lucro em caixa" not in decisao
    assert "aporte do mês" in decisao and "aporte do mês" not in analistas
    assert "ignorado" not in analistas
    assert "never cite a figure from it as current" in decisao


@pytest.mark.unit
def test_a_role_without_a_section_still_gets_the_shared_one(playbook):
    _use(playbook)
    assert "fato, consenso e opinião" in get_knowledge_instruction("pesquisa")


@pytest.mark.unit
def test_no_playbook_adds_no_tokens(playbook):
    _use(None)
    assert get_knowledge_instruction("decisao") == ""


@pytest.mark.unit
def test_a_missing_file_does_not_stop_the_run(tmp_path):
    _use(tmp_path / "nao-existe.md")
    assert get_knowledge_instruction("decisao") == ""
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))


@pytest.mark.unit
def test_the_playbook_reaches_the_portfolio_manager_prompt(playbook):
    from tests.test_structured_agent_prompts import _capturing_llm, _prompt_text
    from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
    from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating

    _use(playbook)
    captured = {}
    llm = _capturing_llm(captured, PortfolioDecision(rating=PortfolioRating.HOLD, executive_summary="x", investment_thesis="y"))
    risk = {"history": "h", "aggressive_history": "a", "conservative_history": "c", "neutral_history": "n",
            "current_aggressive_response": "", "current_conservative_response": "", "current_neutral_response": "",
            "latest_speaker": "Neutral", "count": 1}
    create_portfolio_manager(llm)({"company_of_interest": "PETR4", "risk_debate_state": risk,
                                   "investment_plan": "plan", "trader_investment_plan": "trader plan"})
    assert "aporte do mês" in _prompt_text(captured["prompt"])


@pytest.mark.unit
def test_a_mode_section_only_reaches_its_role_when_the_mode_is_on(playbook):
    _use(playbook)
    assert "risco sacado" not in get_knowledge_instruction("analistas")
    _use(playbook, "credito")
    assert "risco sacado" in get_knowledge_instruction("analistas")
    assert "risco sacado" not in get_knowledge_instruction("decisao")
