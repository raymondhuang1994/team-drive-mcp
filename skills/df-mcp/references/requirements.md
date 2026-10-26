# Operating requirements

## Connected service

The local reader uses Node.js 22+ and Python 3.9+ on Windows, macOS or Linux. Source selection belongs to explicit configuration; no MCP tool can add or change a root. Use `team_drive_status` and the declared schemas to identify the connected release/capabilities, source identity, health, current job and storage mode. Do not infer a connection from the presence of this Skill.

Release 0.3 uses lightweight stdio bridges to one managed local broker for the configured source/state. Chats share one index and scan scheduler, with separate session cursors. The broker starts on demand and exits after its last client has disconnected for the configured idle interval (default 60 seconds). Local Unix sockets or Windows named pipes are used; this is not a network or permanent operating-system service. Do not create a new state directory for every chat. Old 0.2 exclusive workers and 0.2.1 isolated pools have different behavior: diagnose the actual version before recommending recovery.

Default service settings are `service.idle_seconds: 60` and `service.max_clients: 64`; these are deliberate administrator configuration, not limits to raise automatically. State is outside every `.codex` directory and `CODEX_HOME`, including physical aliases. Old root-level/pool caches are preserved until explicit maintenance; changing source uses a separate confirmed profile, not an in-place index rebind.

## Source and local outputs

The root is this service's authorization boundary. Sources are opened for reading, and source traversal/links are guarded. On Windows use ordinary fixed local disks: network/removable/device paths, junctions and reparse paths are unsupported. Windows handles can prevent source-directory renaming while open; stop the service before reorganizing it. The boundary does not remove write access from unrelated host tools.

Indexes, snapshots, exports and evidence manifests are source-derived private data outside the root. Keep calculations and reports in separate approved output locations. Do not change source permissions, force cloud hydration or unlock another application's files. Recognized offline/recall files are excluded; Windows cloud reparse files can be excluded even when locally downloaded. An approved ordinary local copy is the supported alternative.

The service scans at startup and polls while alive (default 30 seconds). A completed earlier inventory does not mean a new refresh has finished: inspect `current_job_id` and call `team_drive_job_status`. Refresh after a known change when needed. Use `force: true` after fixing an unchanged parse failure; it is not a general remedy for a deterministic limit.

## Diagnostics and maintenance

From the installed project, `node scripts/doctor.mjs --config '<config.json>'` reads setup metadata without starting a worker, scanning sources or writing state. It reports local paths; redact them before sharing. Offline success does not prove live source access or lock health. The MCP diagnostic CLI requires explicit `--config` or `--demo`; demo means simulated data, not the user's configured corpus.

Use maintenance only for the stated operational need and authorized scope. Preview first; apply deletes only explicitly selected derived files after lease checks. Export-age cleanup preserves bundle manifests and all exports they reference; unverified bundle references fail closed. Index reset preserves evidence artifacts. Source-identity replacement requires an explicit configuration/maintenance decision, never an automatic retry flag. Never delete lock files to evict a live service. Rebuild from sources only when the reported recovery action calls for it. A closed old MCP transport needs a fresh client connection; a configuration edit cannot revive that pipe.

## Scope and limits

An approved source registry and metric dictionary help establish project/period/status, currency and deduplication. The reader does not automatically decide business authority. Use explicit user scope; ask only when unresolved plausible definitions materially change the answer.

No SharePoint/Teams login, employee permission synchronization, OCR, image/layout understanding, macros, workbook recalculation, arbitrary SQL/code execution or guaranteed atomic cross-file snapshot. Runtime limits and format warnings take precedence over prose examples. macOS/Windows have input/output/time bounds, not Linux's additional parser address-space limit.
