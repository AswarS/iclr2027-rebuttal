## Problem Description

When a system uses sentinel values (e.g., empty strings, `None`, special constants) to represent logical states like "always true" or "no constraint" within expression compilation, these sentinels are designed for a specific rendering context (e.g., SQL WHERE clauses). However, expression composition mechanisms—such as annotations, subqueries, or wrappers—can transport these same expression objects into entirely different rendering contexts (e.g., SELECT projections, GROUP BY clauses, ORDER BY). In these alternate contexts, the sentinel has no valid interpretation and produces syntax errors, crashes, or silently wrong output.

The asymmetry is particularly insidious: one polarity of an edge case (e.g., filtering on an empty set) may already have a valid literal fallback (`0 = 1`), while the negated polarity produces the raw sentinel (an empty string) because the "always true" case was never expected to need a concrete representation outside its original context.

## Root Cause Analysis

The root cause is **context-bound reasoning during sentinel design**. Developers introduce sentinel values (like an empty string meaning "this expression is unconditionally true, so emit nothing in the WHERE clause") with the implicit assumption that the expression will only ever be rendered in that one context. This assumption holds until composition mechanisms allow the expression to cross context boundaries.

The deeper principle is that **sentinel values encode implicit contracts about rendering context**. An empty string is not a universal representation of "true"—it is a context-specific instruction meaning "omit me from this clause." When the expression migrates to a SELECT or GROUP BY clause, "omit me" is not a valid instruction; a concrete value is required. The sentinel's contract is violated silently, producing malformed output.

Negation exacerbates this because the non-negated edge case often has an explicit fallback (e.g., `0 = 1` for "always false"), while the negated case falls through to the sentinel path that was only designed for the filter context.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **crash-exception**: SQL syntax errors when edge-case expressions appear in annotations, subqueries, or aggregations (contexts other than WHERE)
  - **wrong-output**: Silently empty or malformed SQL fragments where a concrete value expression is expected
  - **Asymmetric behavior**: One polarity of an edge case (e.g., empty queryset exclusion) works correctly, while the opposite polarity (e.g., empty queryset filtering with negation) crashes
  - Valid SQL in `WHERE` context but broken SQL when the same expression is wrapped in `Subquery()`, used in `.annotate()`, or appears in `GROUP BY`

### 解决步骤
1. **Inventory all sentinel values** in expression compilation. Search for empty strings, `None` returns, or special constants used to represent logical states like "always true," "no constraint," or "match everything."
2. **Map all rendering contexts** where compiled expressions can appear. Go beyond the primary context (e.g., WHERE) to include SELECT/projection, GROUP BY, ORDER BY, HAVING, and subquery wrapping. For each context, determine whether the sentinel is tolerable or produces invalid output.
3. **Trace composition paths** that can transport expressions across context boundaries. Identify wrappers, annotation mechanisms, subquery constructors, and any other facility that re-renders an expression in a different clause position.
4. **Add a context-adaptation layer at the boundary** — typically in the output type's context-specific rendering hook (e.g., `as_sql` for a particular compiler context, or a `resolve_expression` override). In this layer, detect the sentinel and substitute a context-appropriate concrete equivalent (e.g., replace empty string with SQL literal `1` for true, `0` for false).
5. **Ensure polarity symmetry**: For every edge case that has a valid fallback in one polarity (e.g., "always false" → `0`), verify and implement the corresponding fallback for the opposite polarity (e.g., "always true" → `1`).
6. **Test in all reachable contexts**: Write tests that place the edge-case expression in every rendering context — direct filter, annotation, subquery, aggregation, ordering — for both polarities.

### Why This Works

Fixing at the output type's rendering hook (rather than in the expression resolution logic or the wrapper) is the correct boundary because:

- It **activates only when the expression enters an incompatible context**, preserving existing behavior in the original context where the sentinel is valid and intentional.
- It **centralizes the translation** at the point where context is known, rather than requiring every composition mechanism to be aware of every sentinel convention.
- It respects the principle that **sentinel values are context-dependent encodings** — the fix translates them at context boundaries rather than trying to eliminate them globally, which would risk breaking the original context's behavior.

## Boundary Cases
- **Empty collection with negation**: `~Q(pk__in=[])` produces "always true" sentinel; must emit concrete `1` or equivalent in non-filter contexts
- **Empty collection without negation**: `Q(pk__in=[])` produces "always false"; verify it emits `0` in all contexts, not just WHERE
- **Nested subqueries**: Sentinel expressions wrapped in multiple layers of subqueries or annotations — each layer crossing a context boundary
- **Aggregation over sentinel expressions**: `Count` or `Exists` wrapping an edge-case queryset that resolves to a sentinel
- **Database-specific SQL dialects**: The concrete replacement for a sentinel (e.g., `1` vs `TRUE`) may vary by backend; adaptation must be backend-aware
- **Combined expressions**: Sentinel expressions composed with `&`, `|`, or `~` operators before being placed in an alternate context — intermediate composition may mask or propagate the sentinel

## PR Examples
- django__django-15213