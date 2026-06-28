# Preferences

- Default to cloud over local for any new automated strategy/task/skill/routine that comes up in a session. User has unreliable home internet, so local scheduled tasks (Desktop scheduled tasks, local cron, local hooks) may silently fail to fire during an outage. Prefer Claude Code on the web **Routines** (claude.ai/code/routines) — they run on Anthropic-managed cloud infra and don't depend on the user's home connection or machine being on.
- Existing local automations are being migrated to cloud Routines incrementally, one at a time, as they come up in conversation — not all at once. Don't assume migration is complete; ask what's left if relevant.
- Known cloud Routine already set up: "AI Watchlist Auto-Maintenance" — maintains Robinhood custom watchlist list_id `1da26837-4a43-4217-beee-340e2710e969` on agentic account ••••2735 (account_number 977642735). Watchlist-only, never places trades.
