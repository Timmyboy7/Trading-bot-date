# LLM prompt bodies (Make HTTP modules)

Paste the whole file as the module's request content (it is one JSON object).

| File | Make module | Model |
|---|---|---|
| `micro_claude_body.json` | Claude Micro Analyst (10) | claude-sonnet-5-5, full answers incl. thesis_summary/target_price |
| `micro_kimi_body.json` | Kimi Micro Analyst (61, OpenRouter) | moonshotai/kimi-k3, sparse answers |
| `micro_gpt_body.json` | GPT Micro Analyst (62, OpenRouter) | openai/gpt-6.1-sol, sparse answers |
| `macro_body.json` | Claude Macro / Sector Analyst (7) | claude-sonnet-5-5 |

Step 9 (2026-10-12): selection is by 12-1 momentum, the committee filters. data_anomaly is narrowed to
genuinely wrong data / unhandled one-offs (the code already skips REIT P/E+leverage and bank FCF+leverage,
scores negative equity as max leverage, caps one-off gains, drops earnings growth from a tiny base, flags
P/E > 150 and data gaps); cluster labels must name the narrowest shared driver; the overlay is logged only.
Output fields are unchanged, so select-basket parses them as before.

Macro (step 9): judges sector TREND BREAKDOWN only, with fixed counting rules (avoid = at least 3 candidates and more
than half with ret_3m <= -10% AND >= 20% below their 1-year high; favor = more than half up over 3 months and within
10% of the high; else neutral). 'avoid' only raises the entry bar for new names (reconcile); no sells. News, rates and
the economy are the Risk Analyst's job. On the 2026-10-11 data: no avoid (old prompt: 4 sectors avoided).
