# Reading workflow

## Scope and health

Call status and confirm the connected source identity, service capabilities, coverage and current job when provided. On older services use job_status to establish whether a scan is running. For a lookup, a few verified excerpts may suffice. Totals, rankings, cross-file comparisons and absence claims require a defined population: project, period, source set, approval status, currency and deduplication keys as applicable.

Enumerate that population through every list page; track exclusions and failed relevant files. If pagination changes generation/session, restart enumeration. Request refresh when freshness matters, then inspect job completion and failures. Do not repeatedly queue identical jobs or busy-poll. Cancel only a job no longer needed or explicitly stopped by the user.

## Find and verify

Search within the smallest appropriate prefix using names, project IDs, meaningful terms and aliases. Multi-term searches can match evidence across a file; ranking and snippets are candidate selection aids. Search does not prove that every business-relevant source was found.

Choose sources by explicit approval/applicability/supersession evidence, not filename or mtime alone. Disambiguate duplicate filenames by relative path and identity. Equal hashes identify byte-identical copies, not which business record should be counted.

Inspect structure, version and warnings, then read the relevant range with `expected_version`. Include the fact's header, units, notes and exceptions. Inspect groups give segment offsets; selectors use source locations (CSV rows, XLSX sheet/rows, PDF page, PPTX slide). With a selector, `start` is the offset within matching segments; there is no A1 column clipping. Text `line_bucket` ranges are navigation buckets, not the document's actual extent.

Follow relevant pagination with the same selector/version. A final selected page does not prove the whole file was read. Partial text extraction may support a bounded finding; retain explicit extraction gaps, including PDF pages without usable text. If the source changes, discard the mixed-version chain and restart that file.

## Collect and compute

For multiple sources, use `team_drive_evidence_bundle` when available, supplying inspected file IDs/versions and a plain-language scope. Check its manifest, per-file results and gaps before computing. A bundle keeps evidence together; it cannot certify that the chosen population is complete or approved, and its observation window is not a transactional folder snapshot.

On an older service, export each source with its expected version and keep an equivalent manifest: included/excluded files, versions, locators, warnings/gaps, observations and intended filters. Export includes all supported segments, not a prior read selector. Pass returned absolute artifact paths only to authorized local analysis tools; do not upload them by implication.

Calculate with deterministic code/tools, exact decimal money arithmetic, explicit currency/rounding, agreed business filters and deduplication keys. Reconcile segment counts with actual business rows. When relevant inputs are missing or partial, resolve them or label a bounded subtotal rather than an unconditional total/ranking.

## Answer

Lead with the finding and cite exact relative file, returned locator and source version. For exhaustive work state the population, exclusions, gaps, observation window and calculation method to the extent needed for verification. Public research can supply separately sourced public facts; it cannot replace an internal approval, budget or contract term.
