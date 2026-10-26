# Evidence and recovery

Preserve identity (relative path plus file ID), version, actual locator, coverage/gaps, source-check timing and export provenance. A content version identifies bytes, not approval status. `row_count` in JSONL exports counts segments, not business records. Keep absolute artifact paths and full private traces out of public answers.

| Condition | Decision |
|---|---|
| Tools absent / invalid configuration / version mismatch | Explain the observed setup issue. Use offline doctor with an explicit configuration; do not substitute the demo library or claim Skill text provides access. |
| `SERVICE_BUSY`, `SERVICE_CAPACITY` or legacy `STATE_POOL_EXHAUSTED` | Preserve the configuration. Retry only as advised after a client/lease is released; do not proliferate state directories. Check the reported version/storage mode. |
| `BACKEND_UNAVAILABLE` / interrupted request | Retry on the existing MCP transport if marked retryable. Do not assume an interrupted write was undone or replayed; inspect job/artifact state first. After recovery restart session-bound pagination. |
| `Transport closed` | Reconnect or open a new client session. Changing files cannot revive a client-closed pipe. |
| `SERVICE_CONFIGURATION_CONFLICT` / `SERVICE_PROTOCOL_MISMATCH` | Stop/reconnect the matching service using the documented procedure. Do not mix configurations or silently alter source/state. |
| Source outside root, root/state identity changed, unsafe state, symlink/junction/reparse rejection | Stop using the affected path. Stay inside the authorized source; no automatic permission changes, root widening or deletion. |
| `INDEXER_UNHEALTHY`, recoverable checkpoint / `STATE_REBUILD_REQUIRED` | Follow the actual recovery status. Only explicitly rebuild disposable state when recovery cannot complete; never reset the source or erase live locks. |
| Cloud placeholder, sharing-locked, missing or deleted file | Report the gap. Refresh when appropriate, or use an approved supported copy; do not force hydration/unlock or answer from obsolete cached content. |
| Partial PDF / extraction gaps | Read the available pages for bounded claims and include skipped-page/gap details. A complete total/absence claim remains unsupported if relevant pages are unread. |
| Incomplete inventory, failed relevant files or bundle gaps | Resolve the gap or label a bounded subset. Bundle creation success is not proof of complete evidence or business coverage. |
| Stale source / stale or invalid cursor | Restart the affected file chain or enumeration without the cursor; never combine unmatched generations or sessions. |
| Unsupported, encrypted, damaged or over-limit content | State the actual limitation and a supported scoped alternative; identical retries do not remove deterministic limits. |
| Formula cache missing or stale | Preserve the formula/uncertainty; never substitute zero or claim recalculation. |
| No search results | State the searched scope; try meaningful aliases or enumerate before a stronger absence conclusion. |
| Cancelled/interrupted job | Inspect current job and coverage before refreshing. Cancellation is not successful coverage. |

Use the structured error's `retryable` and `next_action` fields. Do not reveal raw tracebacks. Ordinary answers can be concise: supported claim plus exact source/locator/version, with any material gap beside that claim.
