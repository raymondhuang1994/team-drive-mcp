# Operating requirements and limits

## Runtime prerequisites

The host must connect the `team-drive` MCP server. The public project supplies a TypeScript stdio adapter and a Python 3.9+ local engine using SQLite. This release requires macOS or Linux; Windows is rejected because safe POSIX directory-relative file access is required. Install the locked project dependencies and configure one explicit source root plus a separate state directory using the repository's setup instructions. Do not infer a root from the user's entire home directory.

The configured root is the authorization boundary for this service. The engine refuses symlinks and path traversal. These controls apply to this service, not to unrelated host tools that might have broader permissions. The source must be readable by the operating-system account. Indexes, extracted text and exports contain source-derived information and need the same local protection as the source data.

Only one worker may own a state directory at a time (`STATE_IN_USE` otherwise). Different client processes need distinct state directories or must connect to one managed service. A state directory is bound to its configured root; use a new state directory when changing roots.

The service scans at startup and polls while running (30 seconds by default). It does not install an operating-system file watcher or a permanent background service. A stopped or sleeping computer does not update the index. Run `team_drive_refresh` after a known change when freshness matters, and inspect its job result. Unchanged failed files are not repeatedly parsed by ordinary polling; use `force: true` after resolving the failure when retrying unchanged bytes is appropriate. A file may still change after refresh; evidence reads verify the source version separately.

## Scope and authority

Before a business answer, establish the smallest directory/project/period that covers the question. An approved source registry and metric dictionary are recommended inputs for budget, report and KOL workflows. The reader does not automatically interpret or enforce such business registries.

Use explicit user scope where provided. Otherwise inspect the available sources and state reasonable assumptions. Ask only when different plausible scopes or metric definitions materially change the answer. Do not infer a file's formal status from its filename alone.

## Side effects

- `status`, `list`, `search`, `inspect` and `read` are source reads; indexing may be maintained by the running service.
- `refresh` updates local index state; `export` writes a controlled, generated JSONL artifact below the state directory.
- `job_status` observes jobs; `cancel` requests cancellation of a local indexing job at the next file boundary. The current parser may run until it completes or reaches its timeout.
- None of these tools edits the source documents, grants access, publishes documents or uploads them.

Use the runtime's current tool schemas for exact input names and bounds. Runtime errors and declared limits take precedence over examples in prose. Do not increase limits or change the root implicitly to make a request succeed.

## First-version exclusions

- No SharePoint/Teams/Graph login, cloud synchronization service or permission enforcement between different employees.
- No OCR, image understanding, document rendering, macro execution, workbook recalculation, embedding model or autonomous internet search.
- No business-specific authorization decision, advertising-platform connection, PPT generation or KOL outreach.
- No guaranteed realtime or transactionally consistent snapshot across all source files.
- No guarantee that an arbitrary malformed, encrypted, image-only or oversized file can be parsed.

For OneDrive folders, a visible entry may be an online-only placeholder. Reading it can trigger a download or fail. Use an explicitly selected, locally available test folder; this version does not provide a reliable cloud-placeholder detection API.
