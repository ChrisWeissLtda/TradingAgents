"""BCB macro vendor: aliases, point-in-time cut-off, empty windows and routing."""

import copy
from unittest import mock

import pytest

from tradingagents import default_config
from tradingagents.dataflows import config as config_module, router
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.vendors import bcb

# IPCA as SGS returns it: each month dated the 1st, published the next month.
_IPCA = [
    {"data": "01/06/2026", "valor": "0.16"},
    {"data": "01/07/2026", "valor": "0.07"},
    {"data": "01/08/2026", "valor": "-0.32"},
    {"data": "01/09/2026", "valor": "0.82"},
]


def _response(status=200, rows=()):
    response = mock.Mock(status_code=status)
    response.json.return_value = list(rows)
    response.raise_for_status.side_effect = None if status < 400 else Exception(f"HTTP {status}")
    return response


@pytest.mark.unit
def test_aliases_resolve_to_sgs_codes():
    assert bcb._resolve("selic_target")[0] == 432
    assert bcb._resolve("IPCA 12m")[0] == 13522
    assert bcb._resolve("usd-brl")[0] == 1


@pytest.mark.unit
def test_an_unknown_alias_is_left_to_the_next_vendor():
    with pytest.raises(ValueError):
        bcb.get_macro_data("cpi", "2026-10-01")


@pytest.mark.unit
def test_the_request_uses_sgs_dates():
    with mock.patch.object(bcb.requests, "get", return_value=_response(rows=_IPCA)) as get:
        bcb.get_macro_data("ipca", "2026-11-12", 30)
    params = get.call_args.kwargs["params"]
    assert (params["dataInicial"], params["dataFinal"]) == ("13/10/2026", "12/11/2026")
    assert get.call_args.args[0].endswith("bcdata.sgs.433/dados")


@pytest.mark.unit
def test_a_monthly_figure_is_withheld_until_it_was_published():
    # On 2026-09-05 August's IPCA (dated 2026-08-01) was not yet out; July's was.
    with mock.patch.object(bcb.requests, "get", return_value=_response(rows=_IPCA)):
        out = bcb.get_macro_data("ipca", "2026-09-05", 120)
    assert "**Latest:** 0.07 (2026-07-01)" in out
    assert "-0.32" not in out and "0.82" not in out


@pytest.mark.unit
def test_an_empty_window_says_so():
    # SGS answers a window with no observations with a 404.
    with mock.patch.object(bcb.requests, "get", return_value=_response(status=404)):
        out = bcb.get_macro_data("usd_brl", "2026-11-08", 1)
    assert "No observations of SGS 1" in out


@pytest.mark.unit
def test_the_window_is_capped_at_ten_years():
    with mock.patch.object(bcb.requests, "get", return_value=_response(rows=_IPCA)) as get:
        bcb.get_macro_data("ipca", "2026-11-12", 20 * 365)
    assert get.call_args.kwargs["params"]["dataInicial"] == "14/11/2016"  # 3650 days, two of them leap days


class TestRouting:
    def teardown_method(self):
        config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)

    @pytest.mark.unit
    def test_brazil_aliases_need_no_fred_key(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        set_config({"data_vendors": {"macro_data": "bcb,fred"}})
        with mock.patch.object(bcb.requests, "get", return_value=_response(rows=_IPCA)):
            out = router.route_to_vendor("get_macro_indicators", "ipca", "2026-11-12", 365)
        assert out.startswith("## BCB:")

    @pytest.mark.unit
    def test_other_indicators_still_reach_fred(self):
        set_config({"data_vendors": {"macro_data": "bcb,fred"}})
        with mock.patch.dict(
            router.VENDOR_METHODS["get_macro_indicators"], {"fred": lambda *a, **k: "FRED_OK"}
        ):
            assert router.route_to_vendor("get_macro_indicators", "cpi", "2026-11-12", 365) == "FRED_OK"

    @pytest.mark.unit
    def test_default_chain_tries_bcb_first(self):
        assert default_config.DEFAULT_CONFIG["data_vendors"]["macro_data"] == "bcb,fred"
