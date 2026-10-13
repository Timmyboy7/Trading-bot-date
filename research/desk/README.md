# Research desk

A weekly scheduled Claude task ("Research desk weekly", Sunday afternoon, before the 20:00 weekly run)
researches the basket with web search and the equity-research skills, and writes `latest.json`
(plus a dated copy in `history/`). The daily deep dive (`deep_dive.py`) reads it on every call:

- `kill_criteria`, `next_earnings`, near catalysts and the cluster view go into the News Analyst's input;
- code adds a "wait" for new buying when earnings are `DD_EARNINGS_WAIT_DAYS` (4) calendar days away or closer.

Nothing here can buy or sell by itself. Check what the server loaded: `GET /research-desk`.

## Schema (`latest.json`)

```
{
  "as_of": "YYYY-MM-DD",
  "names": {
    "SYM": {
      "cluster": "memory",                       // short key into "clusters"
      "researched_on": "YYYY-MM-DD",             // last FULL research
      "thesis_short": "one sentence",
      "kill_criteria": ["observable event ...", ...],   // 3-6, concrete, checkable in news
      "next_earnings": "YYYY-MM-DD", "earnings_confirmed": true|false,
      "catalysts": [{"date": "YYYY-MM-DD", "event": "..."}],
      "sources": ["https://..."]
    }
  },
  "clusters": {
    "memory": {"updated": "YYYY-MM-DD", "verdict": "2-3 sentences",
               "signals": [{"signal": "...", "status": "ok|watch|fired"}]}
  }
}
```

Rules for the task: only files under `research/desk/` change; kill criteria are events stated as facts
in news or filings (not price moves, which code handles); no buy/sell recommendations.
