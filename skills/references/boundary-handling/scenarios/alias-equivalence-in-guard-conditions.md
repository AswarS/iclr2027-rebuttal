## Problem Description

When a system uses guard conditions to dispatch between "direct field reference" and "relation traversal" code paths during query construction, the guard may only check the canonical/concrete attribute name of a field. If the field has multiple valid aliases (e.g., a semantic shortcut like `pk`, an alternate accessor name, or a user-defined alias) that all resolve to the same underlying column, references using unrecognized aliases bypass the guard and fall into the relation traversal path. This incorrect dispatch discards contextual modifiers (such as sort direction, filtering operators, or annotations) because the traversal path was never designed to preserve them for what is fundamentally a direct column reference.

This pattern is especially dangerous on models where a single field serves dual roles — for example, in multi-table inheritance where the child model's primary key is simultaneously a foreign key to the parent. In such cases, the relation traversal path actively follows the FK link to the parent, producing semantically wrong query output rather than merely a subtle inefficiency.

## Root Cause Analysis

The root cause is an **incomplete equivalence check** in a branching/guard condition. The code assumes that the concrete database-level attribute name (e.g., `parent_ptr_id`) is the only way a user or framework internals will reference a field directly. However, fields in ORM-like systems commonly have multiple equivalent names:

- The concrete column/attribute name (`parent_ptr_id`)
- Semantic shortcuts (`pk`)
- Accessor names derived from the relation (`parent_ptr`)
- User-defined aliases

When the guard condition only recognizes one of these forms, all other equivalent references are misclassified. The deeper principle is: **whenever code branches on name identity, it must account for all equivalent representations of that identity, not just the canonical one.** Failing to do so creates a latent bug that only manifests when a non-canonical alias is used in combination with contextual modifiers (like descending order), making it appear as a regression on edge cases.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: Query modifiers (e.g., descending sort direction `-pk`) are silently dropped, producing ascending ordering or incorrect joins.
  - **Regression on edge case**: The bug only manifests when using an alias form (like `pk`) on a model where the primary key is also a foreign key (multi-table inheritance), combined with a contextual modifier.
  - **Inconsistent behavior**: Using the concrete column name works correctly, but using a semantic alias for the same field produces different results.

### 解决步骤

1. **Locate all guard conditions** that compare a user-supplied field reference against a field's concrete attribute name to decide between direct-column vs. relation-traversal code paths. Search for comparisons like `name == field.attname` or `name == field.column` in query resolution/compilation logic.

2. **Enumerate all equivalent aliases** for each field that could be supplied by users or internal resolution. This includes the field's `attname` (concrete DB column name), `name` (Python-level field name), semantic shortcuts like `pk`, and any framework-registered aliases. Consult the field's metadata or the model's `_meta` to build the complete set.

3. **Expand the guard condition** to check membership in the full set of equivalent names. For example, change `if name == field.attname:` to `if name in {field.attname, field.name, 'pk', ...}:` or, more robustly, resolve the alias to its canonical form before the guard check so that all equivalent names are normalized before dispatch.

4. **Write targeted regression tests** that exercise each alias form with contextual modifiers on models where the field serves dual roles (e.g., ordering by `-pk` on a child model in multi-table inheritance). Verify that modifiers are preserved and that the generated query references the correct column without unnecessary joins.

### Why This Works

By normalizing or expanding the equivalence check, the guard correctly identifies all forms of a direct field reference, preventing them from falling through to the relation-traversal path. This ensures that contextual modifiers attached to the reference are preserved, because the direct-column code path is designed to carry them through. The fix addresses the root cause — incomplete identity matching — rather than patching symptoms in the traversal path.

## Boundary Cases

- **Multi-table inheritance where the child PK is a OneToOneField to the parent**: The `pk` alias resolves to a field that is both a primary key and a foreign key, making it the most likely trigger for this bug.
- **Proxy models**: The `pk` field may be inherited and have a different `attname` than expected; ensure the guard handles proxy model field resolution.
- **Custom primary keys with explicit `db_column`**: When `attname` and `column` differ from the field's `name`, all three forms must be recognized.
- **Abstract base classes with overridden fields**: Aliases may resolve differently depending on which concrete model is being queried.
- **Chained relations with `pk` shortcut**: e.g., `related_model__pk` where `pk` on the related model is itself a FK — the guard must handle nested alias resolution without infinite recursion.
- **Descending vs. ascending ordering**: The modifier (e.g., `-`) is the canary — if the bug is present, it gets silently stripped during incorrect relation traversal.

## PR Examples

- **django__django-12470**: Ordering by `-pk` on a child model in multi-table inheritance dropped the descending modifier because the `pk` alias was not recognized by the guard condition checking `field.attname`, causing incorrect fallthrough into FK relation traversal logic.