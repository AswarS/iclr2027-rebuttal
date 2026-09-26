## Problem Description

When constructing ORM model objects destined for a specific database connection, field assignment during construction can trigger implicit database queries (e.g., foreign key resolution, deferred attribute loading) before the object's database routing state (`_state.db`) has been established. This causes the ORM to fall back to the global database router, which may lack the necessary context to route correctly — leading to crashes, incorrect routing, or inconsistent state. This pattern is especially dangerous in multi-database setups, migration scripts that target a specific database, and any bulk-creation flow where objects are constructed with keyword arguments in a single expression.

## Root Cause Analysis

ORM model objects carry internal routing state (`instance._state.db`) that determines which database connection is used for any implicit queries triggered by field access or assignment. ORM descriptors — particularly foreign key fields — are not purely in-memory setters; they can trigger lazy-loading or related-object resolution that dispatches actual database queries.

The fundamental ordering dependency is:

> **Database affinity must be established on an object _before_ any field assignment that could trigger context-dependent I/O.**

When objects are constructed via keyword arguments (e.g., `MyModel(fk_field=some_value)`), all field assignments happen inside `__init__`, _before_ the caller has any opportunity to set `_state.db`. The ORM then routes any implicit queries through the default router, which may raise exceptions (e.g., in a custom router that expects a request context) or silently route to the wrong database. The cognitive trap is assuming that object construction is a pure, side-effect-free, in-memory operation — when in reality, ORM descriptors can perform I/O during assignment.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Unexpected exceptions from custom database routers during object construction (not during explicit queries)
  - `OperationalError` or routing errors in migration scripts that specify an explicit `--database` parameter
  - Queries hitting the default database when they should target a specific named database
  - Intermittent failures in multi-database setups that disappear when only one database is configured
  - Stack traces showing descriptor `__set__` methods or related-object resolution inside `Model.__init__`

### 解决步骤
1. **Audit construction sites**: Identify all places where ORM objects are constructed for use with a specific (non-default) database — especially in migration `RunPython` operations, management commands with `--database`, and multi-database bulk flows.
2. **Check for descriptor side effects**: For each model being constructed, determine whether any fields passed as constructor kwargs could trigger implicit queries (foreign keys, `GenericForeignKey`, custom descriptors with `__set__` logic).
3. **Refactor to multi-step initialization**: Replace single-expression construction with a three-phase pattern:
   ```python
   obj = MyModel()                    # Step 1: empty construction
   obj._state.db = target_db          # Step 2: establish database affinity
   obj.fk_field = some_value          # Step 3: assign fields (now safe)
   ```
4. **Convert comprehensions to explicit loops**: If the original code uses list comprehensions or generator expressions for bulk object creation, convert them to explicit `for` loops to accommodate the multi-step initialization.
5. **Validate downstream operations**: Verify that all subsequent operations on these objects (field access, related-object lookups, `save()`, `bulk_create()`) correctly respect the explicitly set `_state.db`.

### Why This Works

By setting `_state.db` before any field assignment, every implicit query triggered by ORM descriptors will be routed through the correct database connection from the start. This respects the fundamental invariant: **an object's behavioral context (database affinity) must be initialized before any operations that depend on that context**. The multi-step pattern makes the ordering dependency explicit and eliminates the hidden coupling between constructor kwargs and database routing.

## Boundary Cases

- **Models with no foreign keys or descriptors**: If a model has only simple fields (CharField, IntegerField, etc.), constructor-based assignment is safe because no implicit queries are triggered. The refactoring is only strictly necessary when descriptor side effects are possible.
- **Default database only**: When only one database is configured and no custom router is in use, the fallback routing happens to be correct, masking the bug. The problem surfaces only when a second database or a strict custom router is introduced.
- **`bulk_create` with `update_conflicts`**: Even after correct construction, `bulk_create` may need the correct `_state.db` to generate database-appropriate SQL (e.g., `ON CONFLICT` syntax varies by backend).
- **Signals and `post_init`**: Custom `post_init` signal handlers may also access fields before `_state.db` is set if they run at the end of `__init__`. The multi-step pattern avoids this by deferring field assignment to after both `__init__` and `_state.db` setup.
- **Abstract base classes and proxy models**: These may introduce additional descriptors or override `__init__`, requiring the same audit for implicit query triggers.

## PR Examples
- django__django-16400