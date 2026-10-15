#!/usr/bin/env python3
"""DCF valuation (EV/EBITDA exit multiple, buyback-adjusted shares) with a WACC x multiple heatmap."""
import argparse
import sys

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf

GRID_SIZE = 10
BASE_IDX = 5  # base case sits at row/col 5 of the 10x10 grid (0-indexed)


def _row(df, names):
    """Return the latest non-null value for the first matching row label."""
    for name in names:
        if name in df.index:
            s = df.loc[name].dropna()
            if not s.empty:
                return float(s.iloc[0])  # columns are sorted newest first
    return None


def fetch_financials(ticker):
    t = yf.Ticker(ticker)
    cf, bs = t.cashflow, t.balance_sheet
    if cf is None or cf.empty or bs is None or bs.empty:
        sys.exit(f"No financial statements found for '{ticker}'.")

    fcf = _row(cf, ["Free Cash Flow"])
    if fcf is None:
        ocf = _row(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
        capex = _row(cf, ["Capital Expenditure"])
        if ocf is not None and capex is not None:
            fcf = ocf + capex  # capex is reported as a negative number
    debt = _row(bs, ["Total Debt"])
    cash = _row(bs, ["Cash And Cash Equivalents",
                     "Cash Cash Equivalents And Short Term Investments"])
    shares = _row(bs, ["Ordinary Shares Number", "Share Issued"])
    if shares is None:
        shares = t.info.get("sharesOutstanding")
    ebitda = _row(t.income_stmt, ["EBITDA", "Normalized EBITDA"]) or t.info.get("ebitda")

    data = {"fcf": fcf, "ebitda": ebitda, "debt": debt if debt is not None else 0.0,
            "cash": cash if cash is not None else 0.0, "shares": shares, "ticker": t}
    if data["fcf"] is None or not data["shares"] or not data["ebitda"]:
        sys.exit(f"Missing Free Cash Flow, EBITDA or share count for '{ticker}'.")

    try:
        data["price"] = t.fast_info["last_price"]
    except Exception:
        data["price"] = None
    return data


def sector_exit_multiple(t, ticker, max_peers=10):
    """Median EV/EBITDA of industry peers, else sector top companies; None if unavailable."""
    info = t.info
    for kind, key in ((yf.Industry, info.get("industryKey")), (yf.Sector, info.get("sectorKey"))):
        if not key:
            continue
        try:
            symbols = [s for s in kind(key).top_companies.index if s.upper() != ticker.upper()]
        except Exception:
            continue
        multiples = []
        for s in symbols[:max_peers]:
            try:
                m = yf.Ticker(s).info.get("enterpriseToEbitda")
            except Exception:
                continue
            if m and m > 0:
                multiples.append(float(m))
        if len(multiples) >= 3:
            return float(np.median(multiples)), f"median of {len(multiples)} {key} peers"
    return None, None


def implied_price(fcf, ebitda, debt, cash, shares, wacc, multiple,
                  growth=0.05, buyback_yield=0.03, years=5):
    """Implied share price; wacc and multiple may be numpy arrays (broadcast)."""
    wacc, multiple = np.asarray(wacc, dtype=float), np.asarray(multiple, dtype=float)
    t = np.arange(1, years + 1)
    flows = fcf * (1 + growth) ** t
    pv_fcf = (flows / (1 + wacc[..., None]) ** t).sum(axis=-1)
    tv = ebitda * (1 + growth) ** years * multiple  # exit multiple on Year-5 EBITDA
    pv_tv = tv / (1 + wacc) ** years
    equity = pv_fcf + pv_tv - debt + cash
    shares_y5 = shares * (1 - buyback_yield) ** years
    return equity / shares_y5


def build_matrix(d, wacc, multiple, growth, buyback_yield):
    waccs = wacc + (np.arange(GRID_SIZE) - BASE_IDX) * 0.004   # 7.0% .. 10.6%
    mults = multiple * (1 + (np.arange(GRID_SIZE) - BASE_IDX) * 0.05)  # -25% .. +20%
    W, M = np.meshgrid(waccs, mults, indexing="ij")
    prices = implied_price(d["fcf"], d["ebitda"], d["debt"], d["cash"], d["shares"],
                           W, M, growth, buyback_yield)
    return pd.DataFrame(prices,
                        index=[f"{x:.1%}" for x in waccs],
                        columns=[f"{x:.1f}x" for x in mults])


def plot(df, ticker, base_price, market_price):
    fig, ax = plt.subplots(figsize=(12, 8))
    sns.heatmap(df, annot=True, fmt=".2f", cmap="RdYlGn", linewidths=0.5,
                cbar_kws={"label": "Implied share price ($)"}, ax=ax)
    ax.add_patch(plt.Rectangle((BASE_IDX, BASE_IDX), 1, 1, fill=False,
                               edgecolor="black", lw=3))
    title = f"{ticker.upper()} DCF - base implied price \\${base_price:,.2f}"
    if market_price:
        title += f" (market \\${market_price:,.2f})"
    ax.set_title(title + "\nBase case outlined")
    ax.set_xlabel("Exit EV/EBITDA multiple")
    ax.set_ylabel("WACC")
    plt.tight_layout()
    if matplotlib.get_backend().lower() in {"agg", "pdf", "ps", "svg", "pgf", "cairo", "template"}:
        print(f"No interactive backend available (using '{matplotlib.get_backend()}'); "
              "no window can open. Run locally with a display and a GUI toolkit such as PyQt6.")
    plt.show(block=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ticker", nargs="?", help="Stock ticker, e.g. AAPL")
    p.add_argument("--growth", type=float, default=0.05, help="FCF growth rate (default 0.05)")
    p.add_argument("--wacc", type=float, default=0.09, help="Base WACC (default 0.09)")
    p.add_argument("--buyback-yield", type=float, default=0.03,
                   help="Annual share count reduction (default 0.03)")
    p.add_argument("--exit-multiple", type=float,
                   help="Override the EV/EBITDA exit multiple (default: sector median)")
    a = p.parse_args()
    ticker = a.ticker or input("Ticker: ").strip()

    d = fetch_financials(ticker)
    if d["fcf"] <= 0:
        print("Warning: latest FCF is non-positive; DCF output will not be meaningful.")

    multiple, source = a.exit_multiple, "user override"
    if multiple is None:
        multiple, source = sector_exit_multiple(d["ticker"], ticker)
    if multiple is None:
        multiple = d["ticker"].info.get("enterpriseToEbitda")
        source = "the company's own current multiple (no sector peers found)"
    if not multiple:
        sys.exit("No EV/EBITDA multiple available; pass --exit-multiple.")

    base = float(implied_price(d["fcf"], d["ebitda"], d["debt"], d["cash"], d["shares"],
                               a.wacc, multiple, a.growth, a.buyback_yield))
    print(f"FCF ${d['fcf']:,.0f} | EBITDA ${d['ebitda']:,.0f} | Debt ${d['debt']:,.0f} | "
          f"Cash ${d['cash']:,.0f} | Shares {d['shares']:,.0f}")
    print(f"Exit multiple {multiple:.1f}x ({source}) | buyback yield {a.buyback_yield:.1%}")
    print(f"Base implied share price: ${base:,.2f}")

    df = build_matrix(d, a.wacc, multiple, a.growth, a.buyback_yield)
    plot(df, ticker, base, d["price"])


if __name__ == "__main__":
    main()
