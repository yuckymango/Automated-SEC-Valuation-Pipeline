# DCF Valuation Model

A command-line tool that takes a stock ticker, pulls its latest annual financials via `yfinance`, runs a five-year discounted cash flow (DCF) valuation with an EV/EBITDA exit-multiple terminal value and buyback-adjusted share count, and displays a 10x10 sensitivity heatmap of implied share price against WACC and exit multiple.

## Quick start

```bash
pip install -r requirements.txt
python dcf.py AAPL
python dcf.py MSFT --growth 0.07 --wacc 0.085 --buyback-yield 0.04 --exit-multiple 18
```

| Argument | Default | Meaning |
|---|---|---|
| `ticker` | prompted if omitted | Stock symbol |
| `--growth` | `0.05` | Annual FCF growth, years 1-5 |
| `--wacc` | `0.09` | Base-case discount rate |
| `--buyback-yield` | `0.03` | Annual reduction in share count |
| `--exit-multiple` | sector median | EV/EBITDA multiple applied to Year-5 EBITDA |

A GUI-capable matplotlib backend is needed for the window to appear; on a headless machine, set `MPLBACKEND=Agg` and replace `plt.show()` with `plt.savefig(...)`.

## Data ingestion

Data comes from the latest annual column of the statements Yahoo Finance sources from SEC filings:

| Input | Source row | Fallback |
|---|---|---|
| Free Cash Flow | Cash flow: `Free Cash Flow` | Operating Cash Flow + Capital Expenditure |
| EBITDA | Income statement: `EBITDA` | `Normalized EBITDA`, then `info["ebitda"]` |
| Total Debt | Balance sheet: `Total Debt` | 0 |
| Cash | Balance sheet: `Cash And Cash Equivalents` | Cash, equivalents and short-term investments; else 0 |
| Shares | Balance sheet: `Ordinary Shares Number` | `Share Issued`, then `info["sharesOutstanding"]` |

The script exits if FCF, EBITDA or share count cannot be found.

### Exit multiple

The multiple is the median `enterpriseToEbitda` of up to 10 industry peers (via `yf.Industry`), falling back to the sector's top companies when fewer than 3 usable peers exist, then to the company's own current multiple. Peer sets can be small (AAPL's industry yields 3 peers), so use `--exit-multiple` when you have a better comparable set. The current market price is fetched only for comparison in the chart title.

## Methodology

For years $t = 1 \dots 5$, with base FCF $F_0$, base EBITDA $E_0$ and growth $g_f$ (the same rate is applied to both):

$$F_t = F_0 (1 + g_f)^t, \qquad E_5 = E_0 (1 + g_f)^5$$

Terminal value uses an exit multiple $m$ on Year-5 EBITDA, discounted at WACC $r$:

$$TV = m \cdot E_5$$

Enterprise value and equity value:

$$EV = \sum_{t=1}^{5} \frac{F_t}{(1+r)^t} + \frac{TV}{(1+r)^5}, \qquad
\text{Price} = \frac{EV - \text{Debt} + \text{Cash}}{S_0 (1 - b)^5}$$

where $b$ is the buyback yield and $S_0$ the current share count. The final per-share value divides by the Year-5 share count.

The Gordon Growth Model is no longer used, so terminal growth is not an input.

## Sensitivity matrix

`implied_price` is vectorised with numpy broadcasting, so all 100 combinations are computed in a single call.

- Y-axis (WACC): 10 values in 0.4% steps, 7.0% to 10.6%.
- X-axis (exit multiple): 10 values in 5%-of-base steps, from 75% to 120% of the base multiple.

A 10-point axis has no exact middle value. The axes are therefore anchored so the base case (WACC 9.0%, base multiple) sits at index 5, one of the four central cells, and that cell is outlined in black on the heatmap. Because of this, the grid is slightly asymmetric. Change `BASE_IDX` or the step sizes in `build_matrix` to adjust.

## Visualisation

A seaborn heatmap (red-yellow-green colour scale) annotates every cell with its implied price in dollars. The title shows the base-case price and the current market price.

## Limitations

- Dividing today's equity value by the Year-5 share count is an approximation: buyback cash is already spent out of FCF, so applying the shrunken share count on top of full FCF double-counts the benefit and pushes the price up. Use a conservative `--buyback-yield`.
- Terminal value is typically the bulk of EV, so the result is dominated by the chosen exit multiple.
- Base WACC is an input, not estimated (no CAPM or capital structure calculation).
- A flat 5% growth rate is applied to a single year of FCF; it ignores cyclicality and mean reversion. Pass `--growth` to override it.
- Negative or volatile FCF produces meaningless valuations; the script warns on non-positive FCF.
- Yahoo Finance data can be incomplete or restated, and banks and other financials generally do not suit FCF-based DCF.
- Debt and cash are taken as reported on the balance sheet, with no adjustment for leases, minorities, or preferred stock.

This is an educational tool and not investment advice.