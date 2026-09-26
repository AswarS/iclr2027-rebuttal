## Problem Description

When a system has multiple code paths that perform the same fundamental operation — bulk-loading interdependent records into a persistent store — one path may have evolved robust safeguards (e.g., transactional constraint deferral) while another path, written independently, lacks those same protections. The unprotected path fails when record insertion order cannot satisfy referential integrity constraints incrementally, such as when circular foreign key dependencies exist or when the serialization order was designed for a different concern (e.g., natural key resolution) and does not guarantee a valid topological insertion order.

This is a **symmetry-breaking** problem: two equivalent operations exist in the codebase, but only one carries the necessary safeguards, because the second was implemented without recognizing it as logically equivalent to the first.

## Root Cause Analysis

The root cause is twofold:

1. **Symmetry-breaking across equivalent code paths.** Developers implement a second code path for the same logical operation (deserialize-and-persist a dataset) without auditing the first path for hard-won solutions. The first path (e.g., fixture loading) already wraps inserts in a transaction with constraint checks disabled, but the second path (e.g., a general deserialization utility) was written independently and assumes insertion order alone is sufficient.

2. **Implicit assumption violation regarding ordering.** The serialization-order algorithm was designed for a specific concern (e.g., resolving natural key dependencies) and makes no guarantee about foreign key insertion order. Developers assume the ordering is "good enough" for referential integrity, when in fact circular or mutual foreign key references make any single linear order insufficient — no topological sort exists for cycles.

Together, these cause crashes (integrity constraint violations) or inconsistent state when records with circular dependencies are deserialized through the unprotected path.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `IntegrityError` or foreign key constraint violation exceptions during deserialization/import of serialized data
  - Failures are **order-dependent**: the same dataset succeeds through one code path (e.g., `loaddata`) but crashes through another (e.g., programmatic `deserialize` + `save`)
  - Failures appear only with certain datasets that contain circular or mutual foreign key references
  - The error is non-deterministic with respect to model ordering, since serialization order varies by context

### 解决步骤
1. **Audit for equivalent operations.** Search the codebase for all code paths that perform the same logical operation (bulk-loading serialized records into the database). Compare their constraint-handling strategies and identify any path that lacks transactional wrapping or constraint deferral.
2. **Wrap the deserialization loop in a transaction.** Ensure all record saves occur within a single atomic transaction so that the database sees the full set of records before any final commit.
3. **Explicitly disable constraint checks for the duration of the bulk insert.** Do not rely solely on deferred constraints, as not all database backends support native constraint deferral. Use the backend's mechanism to suppress constraint enforcement entirely during the insert window.
4. **Re-enable constraint checks and run an explicit verification pass.** After all records are saved, restore constraint enforcement and execute a constraint validation check to catch any genuine violations (as opposed to ordering artifacts).
5. **Unify or share the safeguard logic.** Extract the constraint-handling strategy into a shared utility or ensure the second code path explicitly mirrors the first, so future changes to one are reflected in the other.

### Why This Works

When records have mutual or circular foreign key references, no linear insertion order can satisfy all constraints incrementally — the problem is mathematically unsolvable without deferral. By disabling constraint checks during the insert phase and validating holistically afterward, the system sidesteps the ordering problem entirely. Wrapping in a transaction ensures atomicity: either all records load successfully and pass validation, or the entire operation rolls back cleanly. Mirroring the strategy from an already-correct code path ensures that battle-tested logic is reused rather than reinvented with gaps.

## Boundary Cases
- **Circular foreign key dependencies**: No valid topological insertion order exists; constraint deferral is the only correct approach, not a reordering heuristic.
- **Database backends without native deferred constraints**: The solution must explicitly disable and re-enable constraint checks rather than relying on `DEFERRABLE INITIALLY DEFERRED`, which is not universally supported (e.g., MySQL/SQLite handle this differently than PostgreSQL).
- **Genuine constraint violations in the data**: The post-insert verification pass must distinguish between ordering artifacts (benign) and actual data integrity problems (real errors), ensuring bad data is still rejected.
- **Partial failure and rollback**: If the verification pass detects a real violation, the transaction must roll back all inserts to avoid leaving the database in an inconsistent state.
- **Self-referential foreign keys**: A single model referencing itself can trigger the same issue if a parent record appears after its child in serialization order.

## PR Examples
- django__django-12453