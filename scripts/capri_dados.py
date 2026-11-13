"""Capri: busca os dados de mercado do painel da carteira (sem IA) e grava um JSON.

Fontes: Investidor10 (cotação dos ETFs/BDRs; Yahoo se falhar), Yahoo (índices, VIX,
EWZ, Brent, dólar, ouro, juro de 10 anos dos EUA), TD Monitor (Tesouro Direto),
painelbancario (curva de DI da ANBIMA) e IBGE/SIDRA (IPCA em 12 meses).
Uma fonte que falha vira uma entrada em "erros"; as outras seguem.
"""
import argparse, datetime as dt, json, re, sys

import requests
import yfinance as yf

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
# chave do painel -> símbolo no Yahoo
MERCADO = {"^BVSP": "^BVSP", "^SPX": "^GSPC", "^VIX": "^VIX", "EWZ": "EWZ", "BZUSD": "BZ=F",
           "USDBRL": "BRL=X", "^NDX": "^NDX", "GCUSD": "GC=F", "^RUT": "^RUT", "10 Year": "^TNX"}


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=30, **kw)
    r.raise_for_status()
    return r


def serie(sym):
    """Preço e variações (%) a partir dos fechamentos diários do último ano."""
    h = yf.Ticker(sym).history(period="13mo", interval="1d", auto_adjust=False)["Close"].dropna()
    if h.empty:
        raise ValueError("sem cotações no Yahoo para " + sym)
    px = float(h.iloc[-1])
    var = lambda n: round((px / float(h.iloc[-1 - n]) - 1) * 100, 2) if len(h) > n else None
    ano = h[h.index.year < h.index[-1].year]
    return {"price": round(px, 4), "d1": var(1), "d5": var(5), "m1": var(21),
            "ytd": round((px / float(ano.iloc[-1]) - 1) * 100, 2) if len(ano) else None,
            "asof": h.index[-1].strftime("%Y-%m-%d")}


def investidor10(tk):
    tipo = "bdrs" if tk.endswith(("34", "35", "39")) else "etfs"
    texto = re.sub(r"<[^>]+>", " ", get(f"https://investidor10.com.br/{tipo}/{tk.lower()}/").text)
    m = re.search(r"valor\s+atual\s*R\$\s*([\d.]+,\d+)", texto, re.I)
    if not m:
        raise ValueError("valor atual não encontrado na página")
    return float(m.group(1).replace(".", "").replace(",", "."))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="IBOB11,LFTB11,SPXU11,BIAU39,SMAL11")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "mercado": {}, "etfs": {}, "erros": {}}

    for chave, sym in MERCADO.items():
        try:
            s = serie(sym)
            if chave == "10 Year" and s["price"] > 20:  # ^TNX antigo vinha x10
                s["price"] = round(s["price"] / 10, 3)
            out["mercado"][chave] = s
        except Exception as e:
            out["erros"][chave] = str(e)[:200]

    for tk in [t.strip().upper() for t in a.tickers.split(",") if t.strip()]:
        try:
            out["etfs"][tk] = {"preco": investidor10(tk), "fonte": "Investidor10"}
        except Exception as e1:
            try:
                s = serie(tk + ".SA")
                out["etfs"][tk] = {"preco": round(s["price"], 2), "fonte": "Yahoo (" + s["asof"] + "; Investidor10 falhou: " + str(e1)[:80] + ")"}
            except Exception as e2:
                out["erros"][tk] = f"Investidor10: {e1}; Yahoo: {e2}"[:300]

    try:
        j = get("https://api.tesourodiretomonitor.com.br/api/taxas/atuais").json()
        out["td"] = j.get("data") or []
    except Exception as e:
        out["erros"]["Tesouro"] = str(e)[:200]

    try:
        j = get("https://painelbancario.com.br/data/curva_juros.json").json()
        out["di"] = {"curvas": (j.get("curvas") or [])[-10:], "vertices": j.get("vertices"), "labels": j.get("labels")}
    except Exception as e:
        out["erros"]["Curva de DI"] = str(e)[:200]

    try:
        j = get("https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2265/p/last%201?formato=json").json()
        out["ipca"] = next(x for x in j if x.get("D2C") == "2265")
    except Exception as e:
        out["erros"]["IPCA"] = str(e)[:200]

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": {k: len(out.get(k) or []) for k in ("mercado", "etfs", "td")}, "erros": out["erros"]}, ensure_ascii=False))
    # falha o job só se nada veio
    sys.exit(0 if out["mercado"] or out["etfs"] or out.get("td") else 1)


if __name__ == "__main__":
    main()
