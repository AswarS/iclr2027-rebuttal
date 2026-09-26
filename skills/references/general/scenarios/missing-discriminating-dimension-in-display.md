## Problem Description

When a CLI or UI component renders a tabular listing of registered entities (e.g., routes, endpoints, resources), the display schema may cover only a subset of the dimensions that actually distinguish entries in the underlying data model. As the system evolves to support additional partitioning dimensions — such as host-based routing, subdomains, tenants, or API versions — entries that are internally distinct become visually indistinguishable in the output. Users see duplicate-looking rows with no way to tell them apart, leading to confusion, misdiagnosis of configuration issues, and eroded trust in the tooling.

This pattern emerges whenever a display layer was designed under the implicit assumption that a fixed set of columns (e.g., path + HTTP method) fully identifies each entity, and the system later grows a new discriminating dimension that the display never learned about.

## Root Cause Analysis

The root cause is **display incompleteness relative to the data model's identity dimensions**. Every attribute that participates in making one entity distinct from another constitutes part of that entity's identity. When the display omits any such attribute, it projects multiple distinct entities onto the same visual representation, creating ambiguity.

The cognitive trap is **freezing the mental model of entity identity at design time**. The original developer built the display when only certain dimensions mattered (e.g., single-host deployment), so they naturally equated "entity identity" with the columns they chose to show. When the system later added a new partitioning dimension (e.g., `host` or `subdomain`), no one revisited the display contract because the existing columns still *seemed* sufficient — the new dimension was invisible in the common case. The assumption that the output schema covers all meaningful variation was never explicitly stated, so it was never explicitly challenged.

A secondary structural cause is **parallel-list column construction**: when the table is built from independent per-column lists rather than a unified list-of-rows, adding or conditionally including a new column requires touching every list in lockstep, making the omission more likely to persist.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Partial result / wrong output**: The rendered table shows rows that appear identical but correspond to distinct internal entities.
  - **User reports of "duplicate" entries** in CLI output or UI tables, especially after enabling multi-tenancy, subdomain routing, host-based routing, or API versioning.
  - **Sorting or filtering produces unexpected results** because the hidden dimension silently groups or reorders entries in ways the user cannot see.

### 解决步骤

1. **Audit the data model for all discriminating dimensions.** Enumerate every attribute that can make two otherwise-identical entries distinct. For route-like entities this includes host, subdomain, namespace, version, tenant — not just path and method. Compare this full set against the columns currently rendered.

2. **Conditionally include the missing column at render time.** Detect whether any entry has a non-default (non-empty, non-wildcard) value for the additional dimension. If so, add the column to the output; if all values are uniform/default, omit it to avoid clutter in the simple case. This preserves backward-compatible output for users who don't use the advanced feature.

3. **Label the column according to the active configuration mode.** If the system supports multiple modes that use the dimension differently (e.g., full-host matching vs. subdomain matching), choose the column header that matches the active mode so terminology is accurate and non-confusing.

4. **Extend sorting and filtering to cover the new column.** If the display supports user-controlled sorting or filtering, register the new dimension as a valid option. Handle gracefully the case where a user requests sorting by a conditionally absent column (e.g., silently fall back to default order or emit a clear warning).

5. **Refactor parallel-list rendering to a row-based structure.** If the table is built from separate parallel lists per column, refactor to a unified list-of-rows (list of lists or list of dicts). This makes it trivial to conditionally add or remove columns, to sort by any column index, and to prevent future omissions when new dimensions are introduced.

### Why This Works

The solution restores the invariant that **every identity-contributing dimension is representable in the display**. Conditional inclusion ensures the fix is non-disruptive for the common simple case while guaranteeing that users of advanced features receive the disambiguating information they need. Refactoring to a row-based structure eliminates the structural friction that made the omission easy to introduce and hard to notice, making the system resilient to future dimension additions.

## Boundary Cases

- **All entries share the same value for the new dimension (e.g., single-host deployment).** The column should be omitted entirely to avoid unnecessary noise and preserve backward-compatible output.
- **Mixed entries where some have a value and others don't.** Entries without a value for the optional dimension should display an empty cell or a sensible default label (e.g., `*` for wildcard host), not cause a rendering error.
- **User requests sorting by the conditionally absent column.** The system should either fall back to default sort order gracefully or inform the user that the column is not applicable in the current configuration.
- **Multiple optional dimensions exist simultaneously (e.g., both host and version).** The conditional-inclusion logic must evaluate each dimension independently; the presence of one should not suppress or force the display of another.
- **Very long dimension values (e.g., full hostnames) distorting table layout.** Consider truncation or adaptive column widths to maintain readability.

## PR Examples

- **pallets/flask#5063**: The Flask CLI `routes` command displayed only endpoint, methods, and URL rule — omitting the `host` or `subdomain` dimension. When host-based or subdomain-based routing was configured, distinct routes appeared as identical rows. The fix conditionally adds a "Host" or "Subdomain" column when the application uses the corresponding routing mode, and refactors the rendering to support the additional column cleanly.