# Operating requirements and limits

## Runtime prerequisites

The host must connect the local MCP server exposing `team_drive_` tools. The public project supplies a Node.js 22+ TypeScript stdio adapter and a Python 3.9+ local engine using SQLite. Supported platforms are Windows, macOS and Linux. Install the locked dependencies using the repository setup workflow. The installer asks the user to choose and confirm one source root and displays the separate local state location. Do not infer a root from the user's home directory, add a second root, or scan elsewhere when the configuration is missing. A root change requires the user to run configuration again; no MCP tool can change it.

The configured root is the authorization boundary for this service. The engine refuses symlinks and path traversal. On Windows, use an ordinary folder on a fixed local drive: UNC/network/removable/device paths, junctions and other reparse paths are unsupported; multiply linked source files are rejected. Handles are opened for read access only. Windows directory handles can temporarily prevent renaming or removing an open directory; close the service before reorganizing its root. These controls apply to this service, not to unrelated host tools that might have broader permissions. The source must be readable by the operating-system account. Indexes, extracted text and exports contain source-derived information and need the same local protection as the source data.

Only one worker may own a state directory at a time (`STATE_IN_USE` otherwise). Different client processes need distinct state directories or must connect to one managed service. A state directory is bound to its configured root; use a new state directory when changing roots.

The service scans at startup and polls while running (30 seconds by default). It does not install an operating-system file watcher or a permanent background service. A stopped or sleeping computer does not update the index. Run `team_drive_refresh` after a known change when freshness matters, and inspect its job result. Unchanged failed files are not repeatedly parsed by ordinary polling; use `force: true` after resolving the failure when retrying unchanged bytes is appropriate. A file may still change after refresh; evidence reads verify the source version separately.

## Scope and authority

Before a business answer, establish the smallest directory/project/period that covers the question. An approved source registry and metric dictionary are recommended inputs for budget, report and KOL workflows. The reader does not automatically interpret or enforce such business registries.

Use explicit user scope where provided. Otherwise inspect the available sources and state reasonable assumptions. Ask only when different plausible scopes or metric definitions materially change the answer. Do not infer a file's formal status from its filename alone.

## Source read-only boundary

The installer and runtime do not write probe files, modify, delete, rename, move, or change permissions inside the source. Parsing uses snapshots and temporary files outside the source. Indexes, logs and generated exports belong in the separate state directory; it must not contain the source either. Installing the program inside the selected source is also rejected. Cleanup must stay within application-owned state and installed files.

This is a service boundary, not a sandbox for the entire AI host or every program running under the same user. If operating-system enforcement is required, an administrator must provide a separate restricted identity or isolated environment with read-only source access. Do not change source ACLs as part of ordinary setup or ask for write access merely to read files.

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

For OneDrive folders, a visible entry may be a cloud placeholder. The runtime skips recognized offline/recall files rather than hydrating them. Windows cloud reparse files may be excluded even when their content is locally available. Use an approved copy in an ordinary, nonsynchronized local folder for this release; do not promise complete OneDrive availability detection or cloud-folder support. An unreadable or sharing-locked file is a reported gap, not permission to unlock it, change its ACL, or silently use stale content.
