# Evidence, coverage and recovery

## Required interpretation

Use the tool schema and actual result for field names. Preserve these concepts when answering or handing data to another workflow:

- **Identity:** relative source path and file identity; never replace duplicate filenames with an ambiguous bare name.
- **Version:** content hash/version and observed modification metadata. A version identifies bytes, not approval status.
- **Locator:** line/paragraph, page, slide, sheet or cell information actually returned. Do not manufacture Word page numbers or unsupported cell ranges.
- **Coverage:** selected scope, processed/failed/excluded source state, pagination and parser warnings.
- **Freshness:** when the index was scanned and when the source was checked. An index timestamp is not the source's effective business date.
- **Artifact provenance:** for export, state-relative `artifact_id`, runtime absolute `artifact_path`, input version, segment count and warnings. `row_count` counts exported JSONL segments rather than business rows. Keep outputs local unless the user authorizes transmission; never publish unredacted runtime paths or private tool traces.

## Error response decisions

| Condition | Decision |
|---|---|
| Tools unavailable / invalid configuration | State the missing runtime or configuration. Do not pretend Skill instructions provide file access. |
| Source outside root / symlink rejected | Stay within the approved root. A new root requires an explicit configuration decision. |
| Source missing / deleted | Refresh when appropriate, then locate an authorized replacement. Do not answer from an obsolete cached excerpt. |
| Index incomplete / failed files | Use only the clearly bounded verified subset. An exhaustive answer remains incomplete until relevant gaps are resolved. |
| Source or pagination version changed | Restart the affected file read or enumeration. Never join pages from different generations without qualification. |
| Unsupported, encrypted, damaged or image-only content | Identify the limit and request a supported or separately processed copy where necessary. |
| Size / extraction / time limit | Return the reported limit and actionable scoped alternative. Do not promise retries will solve a deterministic cap. |
| Formula cache absent / possibly stale | Preserve the formula and uncertainty. Do not substitute zero or claim recalculation. |
| No search matches | Say no match was found in the searched/indexed scope. Try a meaningful alias or enumerate relevant files before stronger absence claims. |
| Export is partial | Do not use it for an unqualified complete statistic; account for missing units or narrow the task explicitly. |
| Job cancelled or process interrupted | Inspect persisted status and refresh as needed. A cancelled job is not successful coverage. |

The service's structured tool errors distinguish failures from an empty successful result. Read the error's next action rather than reproducing internal stack traces or absolute environment paths.

## Suggested answer forms

Lookup: “The approved source states X. Source: relative path, returned locator, source version. The cited section applies to period Y.”

Partial result: “Within the N verified source files, the subtotal is X under the stated scope. M relevant files could not be read, so this is not the complete total. Missing: …”

Conflict: “Source A states X and source B states Y. Their status/period does not establish which supersedes the other. The supported conclusion is …; the unresolved issue is …”

Use concise prose for ordinary questions. The evidence requirements do not require a long audit report for every lookup.
