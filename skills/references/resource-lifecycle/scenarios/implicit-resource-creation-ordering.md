## Problem Description

When a code generation or operation sequencing pipeline produces a series of operations, some operations **implicitly create resources** (e.g., database columns, fields, schema elements) as a side effect of what appears to be a metadata or configuration change. If the pipeline's ordering logic categorizes these operations by their surface-level purpose rather than their full set of effects, the implicit resource creation may be scheduled *after* other operations (such as index creation or constraint addition) that depend on the resource already existing. This results in a crash or missing-resource error at execution time — the generated sequence is structurally invalid because a dependency is referenced before it is created.

This pattern is especially insidious because the operation "looks like" a metadata change and is grouped with other low-priority or late-phase operations, while the resource it silently creates is assumed to already exist by earlier-scheduled structural operations.

## Root Cause Analysis

The root cause is a **categorization error driven by surface appearance**: the ordering logic classifies operations by their primary stated purpose (e.g., "alter ordering configuration") rather than by their complete set of side effects (e.g., "alter ordering configuration **and** create a new auto-generated field"). This violates the fundamental principle that **operation ordering must respect all data dependencies, including implicit ones**.

The cognitive trap is that developers mentally model each operation as doing "one thing," and assign it to an ordering phase accordingly. When an operation has a hidden resource-creation side effect, that side effect is invisible to the ordering heuristic. Any downstream operation that references the implicitly-created resource will be scheduled based on its own category — potentially before the creating operation — producing an invalid execution order.

This is compounded when multiple code paths exist for generating operation sequences (e.g., "create new entity" vs. "alter existing entity"), because the fix may be applied in one path but missed in another.

## Solution Strategy

### 识别信号
- 观测到的现象: A crash or exception (e.g., `ProgrammingError`, `OperationalError`, missing column/field/resource error) occurs during execution of a generated operation sequence. The error indicates that a resource (field, column, schema element) is being referenced by an operation (index creation, constraint addition, foreign key setup) before the operation that implicitly creates it has been executed. The sequence generation itself completes without error — the problem only manifests at execution time.

### 解决步骤
1. **Audit every operation type for implicit resource creation**: Systematically review all operation types in the pipeline and identify which ones create resources as a side effect — not just modify metadata. An operation that sets a configuration value but also causes a new field, column, or schema element to materialize is a resource-creation operation.
2. **Reclassify implicit-creation operations as structural prerequisites**: In the operation ordering/phasing logic, move these operations into the same phase as explicit resource-creation operations (e.g., field additions, table creations). They must not remain in a metadata or configuration phase that runs after structural dependency consumers.
3. **Add explicit ordering constraints for the implicitly-created resources**: Ensure the ordering graph includes edges from the implicit-creation operation to every operation that references the created resource (e.g., indexes on auto-generated fields, constraints referencing side-effect columns).
4. **Apply the fix across all code paths**: If there are multiple entry points that generate operation sequences (e.g., one for new entities, one for altering existing entities, one for migrations, one for schema diffing), verify that the ordering correction is applied in every path. Audit both "create new" and "alter existing" pipelines.
5. **Write a regression test**: Create a test case where an implicitly-created resource is referenced by a later structural operation (e.g., an index on an auto-generated field), execute the generated sequence, and verify it completes without error and that the ordering is valid.

### Why This Works

Operation ordering must respect **all** data dependencies — including those that arise from side effects, not just from the operation's primary purpose. By reclassifying implicit-creation operations based on their full effect set rather than their surface-level category, the ordering logic correctly treats them as prerequisites for any downstream operation that depends on the created resource. This eliminates the window where a resource is referenced before it exists, making the generated sequence structurally sound regardless of which operations happen to have hidden creation side effects.

## Boundary Cases
- **Multiple implicit resources from a single operation**: An operation may create more than one resource as a side effect (e.g., a composite key change that generates multiple auto-fields). Each implicitly-created resource must be tracked independently for ordering purposes.
- **Circular implicit dependencies**: Two operations may each implicitly create a resource the other depends on. The ordering logic must detect and break such cycles, potentially by splitting one operation into explicit sub-steps.
- **Conditional resource creation**: An operation may only create a resource under certain configurations (e.g., only when a specific backend is in use). The ordering logic must account for the worst case or be backend-aware.
- **Idempotent re-creation**: If the implicit-creation operation is run but the resource already exists (e.g., from a prior migration), the operation must handle this gracefully — the fix should not introduce failures in the "resource already exists" case.
- **Cross-pipeline interactions**: When multiple pipelines contribute operations to the same execution plan (e.g., third-party apps adding migrations alongside core), implicit-creation ordering must be enforced globally, not just within a single pipeline's output.

## PR Examples
- django__django-13265