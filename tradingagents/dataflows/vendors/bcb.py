"""Banco Central do Brasil (BCB) macro vendor, for B3 (``.SA``) tickers.

Reads Brazilian macro series from the BCB's public SGS time-series API
(https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados): the Selic target,
IPCA inflation and the PTAX dollar rate. No key, no auth.

SGS keeps no vintages, so point-in-time rests on two facts: these series are not
revised after release, and a monthly figure is dated the first of its month but
published in the next one. ``PUBLICATION_LAG_DAYS`` keeps a monthly figure out
of a run dated before it was public.
"""
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
REQUEST_TIMEOUT = 30
DEFAULT_LOOKBACK_DAYS = 365
# SGS refuses a window longer than ten years.
MAX_LOOKBACK_DAYS = 3650
MAX_ROWS = 40

# alias -> (SGS code, title, units, frequency)
BCB_SERIES = {
    "selic_target": (432, "Selic target rate (Copom)", "% per year", "Daily"),
    "ipca": (433, "IPCA consumer price inflation, monthly change", "% m/m", "Monthly"),
    "ipca_12m": (13522, "IPCA consumer price inflation, 12-month change", "% y/y", "Monthly"),
    "usd_brl": (1, "PTAX US dollar rate (selling)", "BRL per USD", "Daily"),
}

# IBGE publishes month M's IPCA around the 10th of month M+1; SGS dates it the
# 1st of M. 45 days from the 1st clears that release with a few days to spare.
PUBLICATION_LAG_DAYS = {"Monthly": 45, "Daily": 0}


def _resolve(indicator: str) -> tuple[int, str, str, str]:
    """The series an alias names; ValueError for anything else, so the router tries the next vendor."""
    key = indicator.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in BCB_SERIES:
        raise ValueError(f"'{indicator}' is not a BCB series alias ({', '.join(BCB_SERIES)})")
    return BCB_SERIES[key]


def _fetch(code: int, start: datetime, end: datetime) -> list[dict]:
    """SGS rows in the window; [] when SGS has none (it answers that with a 404)."""
    response = requests.get(
        SGS_URL.format(code=code),
        params={
            "formato": "json",
            "dataInicial": start.strftime("%d/%m/%Y"),
            "dataFinal": end.strftime("%d/%m/%Y"),
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json()


def get_macro_data(indicator: str, as_of_date: str, look_back_days: int | None = None) -> str:
    """A BCB series as a markdown report, holding only what was public on ``as_of_date``."""
    code, title, units, frequency = _resolve(indicator)
    look_back_days = min(look_back_days or DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS)
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    start = end - timedelta(days=look_back_days)
    lag = timedelta(days=PUBLICATION_LAG_DAYS[frequency])

    points = []
    for row in _fetch(code, start, end):
        dated = datetime.strptime(row["data"], "%d/%m/%Y")
        if dated + lag <= end and row.get("valor") not in (None, ""):
            points.append((dated.strftime("%Y-%m-%d"), row["valor"]))

    header = (
        f"## BCB: {title} (SGS {code})\n"
        f"- Units: {units}\n"
        f"- Frequency: {frequency}\n"
        f"- Window: {start:%Y-%m-%d} to {as_of_date}\n"
    )
    if not points:
        return header + f"\nNo observations of SGS {code} published by {as_of_date} in this window."

    (first_date, first_val), (last_date, last_val) = points[0], points[-1]
    summary = (
        f"\n**Latest:** {last_val} ({last_date}) | "
        f"**Change from {first_date} to {last_date}:** {float(last_val) - float(first_val):+.2f}, "
        f"from {first_val}\n"
    )
    shown = points[-MAX_ROWS:]
    note = f"\n_(showing the most recent {MAX_ROWS} of {len(points)} observations)_\n" if len(points) > MAX_ROWS else ""
    table = "\n| Date | Value |\n| --- | --- |\n" + "\n".join(f"| {d} | {v} |" for d, v in shown) + "\n"
    return header + summary + note + table
