# Tool contract quick reference

These inputs describe the local reader. The Skill is named `df-mcp`; the `team_drive_` tool prefix is retained for compatibility. The connected server's declared schema is authoritative if versions differ. Limits below use defaults, not performance guarantees.

| Tool | Inputs | Key result / next step |
|---|---|---|
| `team_drive_status` | none | `coverage`, `last_scan_at`, `limits`, `index_generation`, update/search modes. |
| `team_drive_list` | `prefix?`, `limit?` (default 20), `cursor?` | `files`, `total_matching_files`, `has_more`, `next_cursor`; inventory metadata is not freshly read evidence. |
| `team_drive_search` | `query`, `prefix?`, `limit?` (default 10), `cursor?` | Candidate files ordered by path; `match.ordinal` and snippet help locate a read. `snippet_is_evidence` is false. |
| `team_drive_inspect` | `file_id`, `limit?` (default 20), `cursor?` | Verified `source_version`, file warnings and paginated `structure` groups with zero-based `start`/`end` segment ordinals. |
| `team_drive_read` | `file_id`, `start?` (default 0), `limit?` (default 10), `expected_version?`, `cursor?`, `selector?` | `segments`, locators, version and warnings. Always pass the inspected version for evidence chains. A cursor supplies the next offset; selector filters supported source locations. |
| `team_drive_export` | `file_id`, **`expected_version`**, `format?` (`jsonl` only) | Whole supported extraction, `artifact_id` relative to state, runtime absolute `artifact_path`, version, count and format warnings. No arbitrary output path. |
| `team_drive_refresh` | `force?` (default false) | `job_id`. Force permits retrying unchanged failed files; ordinary scans avoid repeated expensive failure. |
| `team_drive_job_status` | `job_id?` | Latest job if omitted; job state/progress and coverage. |
| `team_drive_cancel` | `job_id` | Requests cancellation at the next file boundary; current parsing is not immediately killed. |

All page `limit` values must be 1–100. `query` accepts 1–500 characters. `prefix` is a root-relative file/directory prefix, not a shell glob. Never invent a `file_id`; obtain it from list/search.

`selector` is an optional nonempty object with these format-specific combinations:

- CSV/TSV: `row_start?`, `row_end?` (1-based inclusive record bounds).
- XLSX: required `sheet` and optional `row_start?`, `row_end?` (1-based inclusive sheet row bounds).
- PDF: `page` (1-based).
- PPTX: `slide` (1-based).
- Other formats: no selector; navigate through inspect groups and original segment offsets.

Do not mix these combinations. Unknown fields, reversed ranges and incompatible format selectors are rejected. There is no A1 column clipping. With a selector, `start` counts matching segments from zero; without one it counts all source segments from zero. Returned segment `ordinal` remains the original file ordinal. Inspect text `line_bucket` boundaries are navigation ranges only; use actual read locators for line citations.

`artifact_path` is intentionally an absolute path returned at runtime for local analysis tools. It is not public-safe metadata: do not publish that path, unredacted tool traces, or private exported content. Export always includes the whole supported extraction; it does not inherit read selectors.

## Coverage fields

`coverage.inventory_complete` concerns the last inventory traversal. `present_files` counts non-deleted entries; `indexed_files` counts `ready` files; `states` reports all observed states; `all_present_files_indexed` requires completed inventory and every present file ready. `business_completeness` remains `not_established` because a parser cannot establish business authority or missing out-of-root sources.

File states include `ready`, `pending`, `failed`, `blocked`, `unsupported`, `oversized`, `online_only`, `stale` and `deleted`. The `online_only` state reflects a detected operating-system condition, not a comprehensive OneDrive availability check. Inspect/read/export require a ready file and validate its whole-content digest.

`extraction_complete: true` means extraction finished within supported format scope. Read `format_warnings` and segment warnings anyway. `truncated: true` mirrors pagination (`has_more`) in this release: follow `next_cursor` to continue. A final page does not establish complete business coverage.

`total_segments` counts the file's complete supported extraction, while `total_matching_segments` counts the selector's matches. `selection_scope` distinguishes filtered segments from whole-file segments. `selection_complete_in_response` means this single response contains the whole selected set; later pages can complete the accumulated set without that field becoming true. `whole_file_in_response` is always false for filtered reads. A zero-match selector returns an empty result with its source version; do not infer a numeric zero from absence of matching cells.

List/search cursors bind method, query, index generation and server session. Inspect/read cursors bind file version and server session; read also binds the selector. Use a cursor only with its original method and parameters; after `STALE_CURSOR` or `INVALID_CURSOR`, restart the affected enumeration/read.

## Resource limits

Default source limit: 256 MiB; uncompressed/output budget: 512 MiB; parser time: 30 seconds per file; maximum 100,000 segments, 8,000 text characters per segment, 512 columns and 2,000 PDF pages. The protocol result budget is 64 KiB and a serialized source segment may not exceed 48 KiB. A limit can reject a file smaller than the byte ceiling if its structure is unusually expensive.

Linux parser workers additionally have an address-space limit. macOS and Windows use input, archive, output and time bounds without the same hard address-space guarantee. Do not claim uniform memory protection or measured capacity across platforms.

## Example call chain

For a clause lookup: status → search with a project term → inspect the selected `file_id` → read at the matching structure group's `start`, passing `expected_version` → inspect returned context/warnings → cite its locator.

For a full total: status/refresh → enumerate every source in the defined scope → inspect every relevant source → export each with its expected version → verify counts, definitions, currency and duplicates → compute deterministically. The tool chain does not supply missing business definitions automatically.

## Local diagnostic client

From the installed project directory, `node scripts/call-tool.mjs --help` prints usage; `node scripts/call-tool.mjs tools` lists the real connected tool schemas. The CLI starts a new local server session and closes it on exit. For ordinary tool calls it waits up to 60 seconds for startup indexing; a refresh call also waits for its indexing job. It cannot share a state directory already owned by another active server. Use a distinct configuration/state for diagnostics or close the old connection deliberately.

A multi-step workflow with cursors belongs in a persistent MCP session, because cursors are session-bound. Large libraries should use a persistent client rather than repeatedly starting the diagnostic CLI or treating its 60-second startup timeout as an indexing success.
