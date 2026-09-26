## Problem Description

When a code generation tool introspects a relational schema and produces model or class definitions, it typically derives reverse accessor identifiers by convention (e.g., from the target entity name). This works under the implicit assumption that each source entity references a given target entity at most once. However, real-world schemas frequently violate this assumption — for example, a table with both `created_by` and `updated_by` columns both referencing a `users` table. When this fan-out duplication exists, the conventionally generated reverse accessors collide, producing duplicate identifier errors or validation failures at runtime.

This is an instance of the broader **implicit uniqueness assumption** anti-pattern in code generation: the generator assumes a property (uniqueness of reference targets within a scope) that holds in the common case but breaks in legitimate edge cases, leading to silently incorrect or invalid output.

## Root Cause Analysis

The underlying principle is a **many-to-one mapping treated as one-to-one**. Within a single source entity, multiple relational fields can point to the same target entity. The code generator's default naming convention derives the reverse accessor solely from the target entity name, which is inherently non-unique when the target is referenced more than once. Because the generator never checks whether a target has already been referenced, it emits duplicate identifiers that cause downstream clashes.

This is a form of **uniqueness assumption bias** — developers naturally expect that a set of references within a single scope will have distinct targets, overlooking that real-world schemas routinely contain multiple foreign keys to the same table (e.g., `sender`/`receiver` → `User`, `origin`/`destination` → `Location`).

## Solution Strategy

### 识别信号
- 观测到的现象: Generated code triggers "reverse accessor clash," "duplicate identifier," or "related name conflict" errors during model validation or compilation.
- 观测到的现象: The generated output contains two or more relational fields in the same source entity that produce identical implicit reverse accessor names.
- 观测到的现象: Inconsistent state where only one of the duplicate references is usable via the reverse accessor, silently shadowing the others.

### 解决步骤
1. **Track referenced targets per source entity.** During code generation, maintain a per-source-entity set that records which target entities have already been referenced by relational fields.
2. **Check before emitting each relational field.** Before generating a relational field definition, look up whether the target entity already exists in the tracked set for the current source entity.
3. **Disambiguate on collision.** If the target has been seen before, generate an explicit disambiguation identifier (e.g., a `related_name`) that incorporates both the source entity name and the specific field/column name, guaranteeing uniqueness.
4. **Preserve defaults when safe.** If the target has not been seen, add it to the tracked set and allow the default implicit naming convention to apply, keeping the generated code clean in the common case.
5. **Extract repeated computations.** Factor out shared transformations (e.g., entity name normalization, snake_case conversion) into a variable computed once per source entity to improve readability and ensure consistency across all generated fields.

### Why This Works

By detecting duplication at generation time rather than relying on downstream validation, the generator produces correct output in all cases. The disambiguation naming pattern mirrors the platform's default reverse accessor convention while incorporating the specific field name, making identifiers both predictable and unique. Applying disambiguation only when a collision is detected preserves the clean, conventional output for the majority of schemas where no duplication exists — minimizing unnecessary noise in generated code while guaranteeing correctness in the edge case.

## Boundary Cases

- **Self-referential entities**: A table with multiple foreign keys pointing to itself (e.g., `parent_id` and `mentor_id` on a `Person` table) — the source and target are the same entity, requiring disambiguation logic to handle this identity case.
- **Single foreign key to a target**: The most common case; disambiguation should **not** be applied, preserving clean default output.
- **Three or more foreign keys to the same target**: The tracking set approach naturally handles any number of duplicates, but generated names must all remain unique — ensure the field/column name component is always included after the first occurrence.
- **Inherited or abstract entities**: If the schema involves inheritance, foreign keys from parent and child entities may both contribute reverse accessors on the same target, requiring cross-entity awareness.
- **Reserved or conflicting identifier names**: The disambiguated name might collide with an existing attribute on the target entity; a secondary uniqueness check or suffix strategy may be needed.
- **Schema evolution**: A previously unique reference becomes duplicated when a new column is added; regenerated code must now include disambiguation where it previously did not, potentially breaking dependent code that relied on the old implicit name.

## PR Examples

- `django__django-15819`: Django's `inspectdb` management command generated model definitions with clashing `related_name` values when a database table contained multiple foreign keys pointing to the same target table. The fix introduced per-model tracking of referenced target tables and explicit `related_name` generation only when duplication was detected.