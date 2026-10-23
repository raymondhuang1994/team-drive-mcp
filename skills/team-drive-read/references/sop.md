# Evidence reading SOP

## 1. Classify the question

**Lookup:** locate a clause, a stated figure, a named project's source, or a specific reference. A small set of verified excerpts may be sufficient.

**Exhaustive:** totals, complete lists, maxima/minima, rankings, absence assertions, comparisons that depend on every member of a group. Define the population before retrieval: project, period, source set, status, currency and deduplication keys as applicable.

“Which project spent the most?” is exhaustive even when the expected answer is one project. “What does the approved policy say?” is lookup, but still requires version/authority selection.

## 2. Establish coverage

Call `team_drive_status`. Determine whether the initial scan finished, an update is running, files failed or were excluded, and supported content is indexed. Global parser completion is not a certificate that every business-relevant file exists in the root.

For exhaustive work, enumerate the defined population with `team_drive_list`, consume every page and record parse status. List/search cursors must belong to the same query and index generation. If a cursor becomes stale, restart enumeration; never merge unmatched pages as a complete set.

If freshness is in doubt, request `team_drive_refresh`, track it with `team_drive_job_status`, and inspect failures. Do not busy-poll or repeatedly launch identical jobs. Use `team_drive_cancel` only for a job no longer needed or explicitly stopped by the user.

## 3. Discover candidates

Search narrow scope first. Try project identifiers, exact filenames, relevant terms and obvious aliases. Chinese character/bigram matching and configured aliases can miss synonyms, abbreviations or unusual formatting; use alternate terms and listing to cross-check. Results are ordered by path, not by semantic relevance.

Search snippets can be stale or omit context. Reopen the candidate with `team_drive_inspect`/`team_drive_read`. For exhaustive work, search helps identify sources but does not replace complete enumeration.

## 4. Select the valid source

Check project/period, declared approval status, applicability and superseding documents. Separate draft, approved and historical versions. When two sources disagree, consult their explicit status or the user's source rules. Record unresolved conflicts.

If names are duplicated, distinguish relative path and source identity. Do not deduplicate solely by filename. Identical content hashes can identify byte-identical copies; different hashes do not establish which document is authoritative.

## 5. Inspect then read

Inspect the structure, version and format warnings. Structure groups return zero-based `start`/`end` segment ordinals; an unfiltered read can start at the relevant group's `start`. Alternatively use the compatible `selector`: rows for CSV/TSV, sheet plus optional rows for XLSX, a PDF page or a PPTX slide. With a selector, `start` is the offset within matching segments, not the original file ordinal. There is no A1 column-range selector. Read the smallest range that includes the fact plus its interpretation: heading, table header, units, notes and applicable exceptions. Pass the returned `source_version` as `expected_version` on subsequent reads and exports.

TXT/Markdown structure `line_bucket` boundaries describe 200-line navigation buckets, not actual source extent. Use the read segment's real line locator for citations; never quote a bucket's end as the document's final line.

For table-like sources, collect all columns needed to disambiguate records. A missing cell is not zero; a saved formula result is not a new calculation. For PDFs and presentations, include limitations of text extraction when the answer depends on visual content.

Read additional pages whenever `has_more` indicates more relevant data, preserving the same selector. `selection_complete_in_response` refers only to the selected population in the current response; `whole_file_in_response` is false for every filtered read. Zero selected records do not prove zero business value. “Last response page” only closes the current selector; it does not prove the entire document or corpus was read. If a version mismatch occurs, discard the mixed-version chain and restart that file.

## 6. Compute or hand off

For a downstream calculation, export the relevant complete source through `team_drive_export`. Preserve metadata, version, warnings and `artifact_id` (relative to state). Pass the runtime absolute `artifact_path` to a local analysis tool when needed. Do not publish runtime paths, complete traces or private exports. A controlled export is source-derived local data, not permission to upload it. The export contains all supported segments of the file, not a previous read selector's subset; apply explicit downstream business filters.

Use a deterministic script or available analytical tool for arithmetic. For money use exact decimal arithmetic and explicit currency/rounding. Apply project/period/status filters, deduplicate using agreed keys and reconcile row counts. This reader does not run user-provided SQL or arbitrary code.

If any relevant source is missing, changed, failed or partial, either resolve the gap or label a clearly bounded subtotal. Do not output an unconditional total, ranking or complete absence statement.

## 7. Answer and cite

Give the conclusion supported by the evidence. Cite each material factual claim with the exact relative file, version and locator returned by the tool. Explain conflicting or unavailable evidence near the affected conclusion.

For exhaustive tasks record: intended population, included/excluded files and records, exclusion reasons, parse failures, versions, observation window and computation method. Excluding irrelevant files is valid when the reason follows the stated scope; silently excluding failed relevant files is not.

For public research after an internal lookup, use the host's authorized research tools only for public facts and show their sources separately. Public search cannot fill a missing internal budget, approval or contract term.
