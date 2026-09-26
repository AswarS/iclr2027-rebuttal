## Problem Description

When a query normalization or lookup processing step modifies one aspect of a query's internal representation (e.g., the SELECT clause), it can silently corrupt a coupled but logically independent aspect (e.g., the GROUP BY clause) that was explicitly configured by the user. This pattern occurs whenever an internal adjustment assumes it can safely modify one query component without side effects on another, but the ORM's internal coupling between components causes the change to cascade and overwrite explicit user intent with derived defaults.

The key characteristic of this pattern is **silent data corruption rather than errors** — the query still executes successfully but returns wrong results because the user's explicit configuration (such as grouping columns) has been replaced by an implicitly derived default during normalization.

## Root Cause Analysis

In many ORM and query-building systems, internal representations of query components are semantically coupled. For example, the SELECT clause and GROUP BY clause may be treated as interdependent: when the SELECT is modified, the system may automatically regenerate or override the GROUP BY to match. This coupling is often a reasonable default behavior for simple queries.

However, when a user has **explicitly configured** one of these coupled components (e.g., specifying `.values('column')` with aggregation to produce a specific GROUP BY), an internal normalization step that modifies the other component (e.g., rewriting SELECT to ensure a single-column output for a subquery comparison) will inadvertently destroy the explicit configuration. The system cannot distinguish between "GROUP BY was auto-derived from SELECT" and "GROUP BY was explicitly set by the user," so it treats both cases identically — overwriting with a new derivation.

The cognitive trap is the **implicit assumption that modifying one query component is an isolated operation**, when in reality the internal coupling makes it a destructive cascading operation that violates the user's explicit intent.

## Solution Strategy

### 识别信号
- 观测到的现象: A subquery with explicit grouping (e.g., `.values()` with aggregation) produces correct SQL in isolation, but when used inside a filter lookup (e.g., `__in`, `__exact`), the GROUP BY clause silently changes to reference the wrong column (e.g., primary key instead of the intended grouping column), producing wrong results without any error.
- The failure mode is **silent wrong output / silent data loss** — no exception is raised, but the result set is incorrect.
- The problem only manifests when the subquery has **explicit grouping**; plain subqueries without GROUP BY are unaffected.

### 解决步骤
1. **Locate the normalization point**: Find the lookup or processing method where the subquery's SELECT clause is modified to prepare it for use in a comparison (e.g., ensuring a single-column output for an `__in` lookup).
2. **Capture the explicit state before modification**: Before the SELECT clause adjustment is applied, save the subquery's current GROUP BY clause into a temporary variable (~1 line). This preserves the user's explicit grouping intent.
3. **Allow the normalization to proceed**: Let the SELECT clause modification execute as designed — it serves a legitimate purpose (ensuring the subquery returns the correct column for comparison).
4. **Restore the preserved state after modification**: After the SELECT adjustment, reassign the saved GROUP BY clause back onto the query object (~1–2 lines). This decouples the GROUP BY from the SELECT modification, preventing the cascading override.
5. **Add regression tests**: Verify that (a) a grouped/aggregated subquery used in a filter preserves its explicit GROUP BY referencing the correct column, and (b) a plain subquery without explicit grouping still has its SELECT and GROUP BY adjusted normally by the lookup machinery.

### Why This Works

The fix respects both concerns: the lookup's legitimate need to control which column the subquery returns (SELECT adjustment) and the user's explicit grouping intent (GROUP BY preservation). Rather than attempting to decouple the internal representation of SELECT and GROUP BY globally — which would be a large and risky refactor — the fix applies a **save-and-restore pattern** at the specific point where the destructive cascade occurs. This is minimal, surgical, and preserves backward compatibility for all cases where the coupling is actually desired (i.e., queries without explicit grouping).

The underlying principle is: **when a normalization step must modify a coupled component, explicitly preserve any user-configured state that would be destroyed by the coupling side effect.**

## Boundary Cases
- **Subquery without explicit grouping**: The SELECT and GROUP BY adjustment should proceed normally — the save-and-restore should be a no-op or should correctly restore the (empty/auto-derived) GROUP BY state.
- **Subquery with multiple aggregation levels**: Nested aggregations where GROUP BY is set at different levels must each be preserved independently if multiple normalization passes occur.
- **Subquery used in different lookup types**: The fix must apply consistently across all lookup types that modify the subquery's SELECT (`__in`, `__exact`, `__gt`, etc.), not just one specific lookup.
- **Subquery with compound GROUP BY**: When the GROUP BY references multiple columns, the entire clause must be preserved, not just a single column reference.

## PR Examples
- django__django-11797