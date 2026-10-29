# Operating requirements

## Connected service

The local reader uses Node.js 22+ and Python 3.9+ on Windows, macOS or Linux. Source selection belongs to explicit configuration; no MCP tool can add or change a root. Use `team_drive_status` and the declared schemas to identify the connected release/capabilities, source identity, health, current job and storage mode. Do not infer a connection from the presence of this Skill.

Releases 0.3 and 0.4 use lightweight stdio bridges to one managed local broker for the configured source/state. Chats share one index and scan scheduler, with separate session cursors. The broker starts on demand and exits after its last client has disconnected for the configured idle interval (default 60 seconds). Local Unix sockets or Windows named pipes are used; this is not a network or permanent operating-system service. Do not create a new state directory for every chat. Old 0.2 exclusive workers and 0.2.1 isolated pools have different behavior: diagnose the actual version before recommending recovery. A newer Skill does not upgrade an existing connection; discover its tools and status capabilities before using 0.4 additions.

Default service settings are `service.idle_seconds: 60` and `service.max_clients: 64`; these are deliberate administrator configuration, not limits to raise automatically. State is outside every `.codex` directory and `CODEX_HOME`, including physical aliases. Old root-level/pool caches are preserved until explicit maintenance; changing source uses a separate confirmed profile, not an in-place index rebind.

## Source and local outputs

The root is this service's authorization boundary. Sources are opened for reading, and source traversal/links are guarded. On Windows use ordinary fixed local disks: network/removable/device paths, junctions and reparse paths are unsupported. Windows handles can prevent source-directory renaming while open; stop the service before reorganizing it. The boundary does not remove write access from unrelated host tools.

Indexes, embedding caches, snapshots, exports and evidence manifests are source-derived private data outside the root. Keep calculations and reports in separate approved output locations. Do not change source permissions, force cloud hydration or unlock another application's files. Recognized offline/recall files are excluded; Windows cloud reparse files can be excluded even when locally downloaded. An approved ordinary local copy is the supported alternative.

The service scans at startup and polls while alive (default 30 seconds). A completed earlier inventory does not mean a new refresh has finished: inspect `current_job_id` and call `team_drive_job_status`. Refresh after a known change when needed. Use `force: true` after fixing an unchanged parse failure; it is not a general remedy for a deterministic limit.

## Optional local model retrieval

Semantic embeddings and reranking are disabled by default. Enabling them requires administrator configuration of a specific model and local HTTP(S) endpoint. Accepted endpoints use localhost or literal loopback/private addresses; arbitrary hostnames, public addresses, embedded credentials, redirects and ambient HTTP proxies are rejected. This is a network call to the configured service, not proof that the model process runs on the same computer. Configure only a service approved to receive the selected queries and source text.

Semantic indexing is bounded and incremental. A failed or partial model index does not turn readable source files into complete semantic coverage; inspect status and per-search diagnostics. Model identity/revision and extraction text/version bind the persistent embedding cache. Available code and synthetic tests do not establish quality, hardware capacity or latency for a real model and team corpus. Validate those with representative questions before treating semantic/rerank results as a quality improvement.

Retrieval model configuration is separate from the agent host's answer model: even local parsing and local retrieval do not guarantee local answer inference. The Skill does not change either configuration or grant transmission permission.

## Diagnostics and maintenance

On 0.4 services, `team_drive_diagnostics` reports bounded operation samples and timing aggregates. Diagnostics are enabled by default and retain at most 1,000 events for seven days; administrator settings can disable collection or change bounded retention. Records contain operation names, timestamps, elapsed time, success and sanitized error codes, never query text, source contents or paths. Retention-limited samples are not all-time usage or answer-accuracy measures. Check `write_failures`; diagnostic write failure does not replace the evidence result. Older services without this tool can use their existing status/doctor workflow.

From the installed project, `node scripts/doctor.mjs --config '<config.json>'` reads setup metadata without starting a worker, scanning sources or writing state. It reports local paths; redact them before sharing. Offline success does not prove live source access or lock health. The MCP diagnostic CLI requires explicit `--config` or `--demo`; demo means simulated data, not the user's configured corpus.

Use maintenance only for the stated operational need and authorized scope. Preview first; apply deletes only explicitly selected derived files after lease checks. Export-age cleanup preserves bundle manifests and all exports they reference; unverified bundle references fail closed. Index reset preserves evidence artifacts. Source-identity replacement requires an explicit configuration/maintenance decision, never an automatic retry flag. Never delete lock files to evict a live service. Rebuild from sources only when the reported recovery action calls for it. A closed old MCP transport needs a fresh client connection; a configuration edit cannot revive that pipe.

## Scope and limits

An approved source registry and metric dictionary help establish project/period/status, currency and deduplication. The reader does not automatically decide business authority. Use explicit user scope; ask only when unresolved plausible definitions materially change the answer.

No HTTP MCP service, shared-drive synchronization, SharePoint/Teams login, employee permission synchronization, OCR, image/layout understanding, macros, workbook recalculation, arbitrary SQL/code execution or guaranteed atomic cross-file snapshot. Runtime limits and format warnings take precedence over prose examples. macOS/Windows have input/output/time bounds, not Linux's additional parser address-space limit.
