# Python tool entrypoint

Paths below are relative to the extracted Skill root. Use the approved Python 3.9+ interpreter. The ZIP vendors pinned pure-Python parser libraries; Node/npm is unnecessary for this entrypoint. Original stdio MCP continues to require its Node runtime.

```text
python scripts/df-tool.py status --config <saved-config.json>
python scripts/df-tool.py search --config <saved-config.json> --params-file <query.json> --paginate
python scripts/df-tool.py list --config <saved-config.json> --params-file <scope.json> --paginate
python scripts/df-tool.py inspect --config <saved-config.json> --params-file <file.json> --paginate
python scripts/df-tool.py read --config <saved-config.json> --params-file <versioned-read.json> --paginate
```

Supported methods are the same 13 engine methods: status, list, search, inspect, read, context, plan, diagnostics, export, evidence_bundle, refresh, job_status, cancel. See tools.md for their parameters; omit the `team_drive_` prefix for CLI method names. Use JSON files to preserve literal paths, Unicode, quotes and query text without shell interpolation. stdout is one JSON result, exit 0 for `ok:true`, otherwise nonzero. Do not hide error results.

## Pagination and scope

The CLI uses one local broker connection per invocation. A cursor is session-bound and cannot be copied into a later CLI invocation. `--paginate` consumes the pages on the same connection, returning `pages` and `pagination_complete`. It supports list/search/inspect/read. Default max-pages is 100, configurable up to 1000. Aggregate output is bounded at 8 MiB. An exhausted budget is explicitly partial; narrow the scope or use versioned export for large files. `pagination_complete:true` only means this query's pages were consumed, not that a business population is complete.

If a permission/version check fails mid-pagination, the CLI discards preceding pages from the response and returns failure. Restart after resolving the reported condition; do not stitch failed attempts together. Without `--paginate`, `has_more` may be true and the CLI removes the unusable next_cursor.

For file reads, pass the exact expected_version from inspect/read. Multiple list pages may race an indexing update: restart after INVALID_CURSOR, not with the old cursor. For statistics, explicitly define source/prefix, collect a full file inventory, inspect failures and use evidence bundles/exports.

## Index readiness

A first status starts the configured local broker and its initial scan. Distinguish connectivity, scanning, and usable coverage. Call status, then job_status for current_job_id. A bounded `--wait-ready 30` can wait for the initial job; a timeout is not a failed index and must not trigger a second index directory. Report unsupported/failed/partial files even when a scan finishes. Scanning polls only while the broker is alive; it is not an installed unattended background service.

## Persistence and host location

The broker reuses the same configured index across invocations/chats. Last-client idle shutdown keeps committed state. Other chats use independent session cursors. This is per-user local IPC, not a multi-user web server.

Run on the company computer or its approved local executor. Pure cloud execution has no implicit access to that computer. A remote existing MCP may be used through its native tools after source verification, but this ZIP does not deploy a remote HTTP MCP server or tunnel.
