# Research desk

A weekly scheduled Claude task ("Research desk weekly", Sunday afternoon, before the 20:00 weekly run)
researches the basket with web search and the equity-research skills, and writes `latest.json`
(plus a dated copy in `history/`). The daily deep dive (`deep_dive.py`) reads it on every call:

- `kill_criteria`, `next_earnings`, near catalysts and the cluster view go into the News Analyst's input;
- a HELD name with a kill criterion hit (last 10 days) or an earnings review verdict "broken" goes to the
  3-model Confirm/Veto committee as a case (flagged_by research_desk); the usual exit rule applies;
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
      "sources": ["https://..."],
      "key_dependencies": [{"name": "Nvidia", "ticker": "NVDA", "why": "largest HBM customer"}],  // 3-6: customers, suppliers, inputs, competitors; ticker if listed in the US (news is fetched for it daily)
      "earnings_preview": "before a report: what in THIS report would break the case (thresholds)",
      "earnings_review": {"date": "YYYY-MM-DD", "verdict": "intact|weakened|broken", "summary": "..."},
      "kill_criteria_hit": [{"criterion": "...", "date": "YYYY-MM-DD", "source": "https://..."}]
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
