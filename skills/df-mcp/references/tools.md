# Tool contract quick reference

These inputs describe the local reader. The Skill is named `df-mcp`; the `team_drive_` tool prefix is retained for compatibility. The connected server's declared schema is authoritative if versions differ. Discover available tools from the connected schema; status is not a substitute for tool discovery. Limits below use defaults, not performance guarantees.

| Tool | Inputs | Key result / next step |
|---|---|---|
| `team_drive_status` | none | `service_version`, source/config identity, shared-service health, `current_job_id` (use job_status for detail), `state_storage`, `coverage`, `last_scan_at` and limits when supported. Older versions omit newer fields. |
| `team_drive_list` | `prefix?`, `limit?` (default 20), `cursor?` | `files`, `total_matching_files`, `has_more`, `next_cursor`; inventory metadata is not freshly read evidence. |
| `team_drive_search` | `query`, `prefix?`, `limit?` (default 10), `cursor?` | Ranked candidate files (use the returned `order` on older versions); `match.ordinal` and snippet help locate a read. `snippet_is_evidence` is false. |
| `team_drive_inspect` | `file_id`, `limit?` (default 20), `cursor?` | Verified `source_version`, file warnings and paginated `structure` groups with zero-based `start`/`end` segment ordinals. |
| `team_drive_read` | `file_id`, `start?` (default 0), `limit?` (default 10), `expected_version?`, `cursor?`, `selector?` | `segments`, locators, version and warnings. Always pass the inspected version for evidence chains. A cursor supplies the next offset; selector filters supported source locations. |
| `team_drive_export` | `file_id`, **`expected_version`**, `format?` (`jsonl` only) | Whole supported extraction, `artifact_id` relative to state, runtime absolute `artifact_path`, version, count and format warnings. No arbitrary output path. |
| `team_drive_evidence_bundle` | `files` (1–50 objects containing `file_id`, `expected_version`), `scope_description?` (default empty string; supply a scope for this workflow) | `artifact_path` / `artifact_id` for the manifest, `files`, `observation_interval`, `all_selected_versions_exported`, `all_selected_text_complete`, and failed/exported counts. `ok: true` means the manifest was created, not that every input succeeded. |
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

`coverage.inventory_complete` concerns the last inventory traversal. `present_files` counts non-deleted entries; `indexed_files` counts `ready` files; `states` reports all observed states; `all_present_files_indexed` requires completed inventory and every present file ready. `partial_files` and `all_present_files_extracted_completely` distinguish ready partial extractions from complete text coverage. `business_completeness` remains `not_established` because a parser cannot establish business authority or missing out-of-root sources.

File states include `ready`, `pending`, `failed`, `blocked`, `unsupported`, `oversized`, `online_only`, `stale` and `deleted`. The `online_only` state reflects a detected operating-system condition, not a comprehensive OneDrive availability check. Inspect/read/export require a ready file and validate its whole-content digest. Ready PDF files may still have `extraction_complete: false`; read `content_coverage.missing_text_pages` and other gaps.

`extraction_complete: true` means extraction finished within supported format scope; it is false for explicit missing-text PDF pages. `content_coverage` gives total/pages-with-text/missing-text pages and `ocr_performed: false`; blank and image-only pages are not automatically distinguished. Read `format_warnings` and segment warnings anyway. `truncated: true` mirrors pagination (`has_more`) in this release: follow `next_cursor` to continue. A final page does not establish complete business coverage.

`total_segments` counts all currently extracted file segments, not proof of extraction completeness, while `total_matching_segments` counts the selector's matches. `selection_scope` distinguishes filtered segments from whole-file segments. `selection_complete_in_response` means this single response contains the whole selected set; later pages can complete the accumulated set without that field becoming true. `whole_file_in_response` is always false for filtered reads. A zero-match selector returns an empty result with its source version; do not infer a numeric zero from absence of matching cells.

List/search cursors bind method, query, index generation and server session. Inspect/read cursors bind file version and server session; read also binds the selector. Use a cursor only with its original method and parameters; after `STALE_CURSOR` or `INVALID_CURSOR`, restart the affected enumeration/read.

## Resource limits

Default source limit: 256 MiB; uncompressed/output budget: 512 MiB; parser time: 30 seconds per file; maximum 100,000 segments, 8,000 text characters per segment, 512 columns and 2,000 PDF pages. The protocol result budget is 64 KiB and a serialized source segment may not exceed 48 KiB. A limit can reject a file smaller than the byte ceiling if its structure is unusually expensive.

Linux parser workers additionally have an address-space limit. macOS and Windows use input, archive, output and time bounds without the same hard address-space guarantee. Do not claim uniform memory protection or measured capacity across platforms.

## Example call chain

For a clause lookup: status → search with a project term → inspect the selected `file_id` → read at the matching structure group's `start`, passing `expected_version` → inspect returned context/warnings → cite its locator.

For a full total: status/refresh → enumerate the defined scope → inspect relevant files → create an evidence bundle (or individual versioned exports on older servers) → check manifest/gaps, counts, definitions, currency and duplicates → compute deterministically. The tool chain does not supply missing business definitions automatically.

## Local diagnostic client

For offline setup inspection use `node scripts/doctor.mjs --config '<config.json>'`; it starts no worker and scans no source files. For live tools use `node scripts/call-tool.mjs tools --config '<config.json>'` or a named tool plus JSON arguments. `--demo` explicitly selects the simulated library. The CLI opens a client session to the managed local service, closes that session on exit, and never implicitly selects a source. Status is immediate; ordinary reads wait up to 60 seconds for initial indexing. A refresh call waits for its job. It does not automatically inspect the configuration of an existing Codex chat.

A multi-step workflow with cursors belongs in a persistent MCP session, because cursors are session-bound. Large libraries should use a persistent client rather than repeatedly starting the diagnostic CLI or treating its 60-second startup timeout as an indexing success.

## Evidence bundle

Provide 1–50 unique inspected file IDs with expected versions. The manifest records the stated scope, source identity, per-file export results, versions and extraction gaps across an observation interval. `files[].status` is `exported` or `failed`; check both `all_selected_versions_exported` and `all_selected_text_complete` before complete calculations. A partial PDF can export successfully without complete text coverage. The manifest can contain private source paths; keep it local. On older connected versions without this tool, use individual exports and retain equivalent provenance.
