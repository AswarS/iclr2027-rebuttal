## Problem Description

When a queryset filter traverses a one-to-many or many-to-many relationship boundary, the underlying SQL JOIN can multiply rows in the result set, violating the implicit assumption that filtering only reduces or maintains result cardinality. This pattern manifests most visibly in UI-facing contexts (such as form field choice lists) where duplicate entries are unexpected and incorrect, but the root cause is a general mismatch between the mental model of "filter = subset" and the reality of JOIN semantics in relational databases.

In the specific case of Django's `limit_choices_to` on ForeignKey or ManyToManyField, a filter condition that references attributes across a one-to-many relationship causes the ORM to generate a JOIN. If a parent record has N matching related records, the JOIN produces N rows for that parent, resulting in N duplicate entries in the form field's dropdown or select widget.

## Root Cause Analysis

The fundamental issue is a **cardinality assumption violation** at the boundary between filtering logic and JOIN semantics:

1. **Mental model mismatch**: Developers (and the original code authors) assume that applying a filter to a queryset can only narrow results — producing a subset of the original set. This holds true when the filter predicate operates on columns of the base table or traverses a many-to-one (ForeignKey forward) relationship.

2. **JOIN-induced row multiplication**: When the filter predicate crosses a one-to-many or many-to-many boundary, the ORM must JOIN to the related table to evaluate the condition. This JOIN can produce multiple rows per base-table record — one for each matching related record. The WHERE clause then keeps all these duplicated rows (since each one satisfies the predicate), resulting in duplicates in the final result.

3. **Invariant erosion**: The forms layer was written under the assumption that the queryset feeding a choice field would naturally contain unique entries. This invariant held for simple `limit_choices_to` filters but eroded when users began specifying filters that traverse reverse or many-to-many relationships — a perfectly valid and documented use case that the original implementation did not account for.

## Solution Strategy

### 识别信号
- 观测到的现象: **Duplicate entries** appear in form field option lists (dropdowns, select widgets, checkbox groups), with the number of duplicates correlating to the number of matching related records (**partial-result / wrong-output**).
- The `limit_choices_to` parameter contains a lookup that traverses a reverse ForeignKey, a ManyToManyField, or any one-to-many relationship (e.g., `{'children__status': 'active'}`, `{'tags__name__in': [...]}`).
- The duplication is data-dependent — it only appears when related records exist and match the filter condition.

### 解决步骤
1. **Locate the forms-layer code path** where `limit_choices_to` is applied to the formfield's queryset. This is typically in the method that constructs the form field for a model field (e.g., `formfield()` or a utility function that applies `limit_choices_to` via `.filter()` or `.complex_filter()`).
2. **Chain `.distinct()`** on the queryset immediately after the `limit_choices_to` filter is applied. This eliminates duplicate rows introduced by the JOIN before the queryset is consumed by the form field widget.
3. **Verify minimality**: Ensure the fix is scoped to the forms/presentation layer only. Do not modify model field definitions, query construction internals, or add `.distinct()` at a lower abstraction level where it could have unintended side effects on aggregation, ordering, or pagination.

### Why This Works

- `.distinct()` collapses the duplicate rows produced by the JOIN back to unique base-table records, restoring the invariant that each choice appears exactly once.
- The fix is applied at the **presentation layer** (forms), which is the correct abstraction level because: (a) the duplication is a presentation concern — form fields must never show duplicate options regardless of query structure; (b) the queryset at this point is used solely for populating a finite choice list, not for complex ordering, pagination, or aggregation that `.distinct()` might interfere with; (c) it follows existing patterns in the codebase for handling JOIN-induced duplication.
- This is a pragmatic fix that addresses the symptom at the exact point where it matters, rather than restructuring the query into an EXISTS subquery (which would be more invasive and risk regressions).

## Boundary Cases
- **Filters that don't cross relationship boundaries**: `.distinct()` is harmless but unnecessary when `limit_choices_to` only filters on the base table's own columns. The overhead is negligible for choice-list-sized querysets.
- **Custom ordering with `.distinct()`**: If a custom ordering references columns not in the SELECT list, some databases (notably PostgreSQL) may raise errors when `.distinct()` is applied. In the context of form field choices, default ordering is typically by the model's primary key or `__str__`, so this is unlikely to be an issue.
- **ManyToManyField with a custom through table**: Filters on through-table attributes are a common trigger for this bug and should be explicitly tested.
- **Chained or nested Q objects in `limit_choices_to`**: Complex filter expressions involving OR conditions across relationships can produce even more aggressive row multiplication; `.distinct()` handles all such cases uniformly.
- **Empty `limit_choices_to`**: When no filter is applied, no JOIN is generated, and `.distinct()` is a no-op in effect.

## PR Examples
- django__django-13315