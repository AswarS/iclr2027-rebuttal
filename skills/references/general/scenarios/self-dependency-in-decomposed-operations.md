## Problem Description

When a schema migration system decomposes a complex field type change (e.g., converting a foreign key to a many-to-many relationship) into a pair of sub-operations — remove the old field, then add the new field — the resulting operations may contain a self-dependency that the operation scheduler fails to resolve. Specifically, if the old field participates in composite constraints (such as unique-together), those constraints must be dropped while the old field still exists. However, without an explicit ordering dependency between the "remove" and "add" halves of the decomposed operation, the scheduler may interleave them incorrectly, causing constraint-removal operations to fail because the field they reference has already been altered or the new field has been introduced prematurely.

## Root Cause Analysis

The fundamental issue is an **implicit assumption violation**: the auto-detection logic assumes that an "add field" operation always represents a genuinely new field with no prior schema presence. In reality, when a field undergoes a type change that requires decomposition into remove-then-add, the "add" is the **second half of a two-phase replacement**. The first half (removal) — along with all dependent cleanup operations like dropping constraints that reference the old field — must complete before the addition proceeds.

Without an explicit ordering dependency between these two halves, the dependency graph has no way to know they are logically coupled. The scheduler is free to reorder them, and when it does, operations that depend on the old field's schema state (e.g., `ALTER TABLE DROP CONSTRAINT`) execute at a point where the field is missing or the schema is in an inconsistent intermediate state. This is an **ordering dependency** problem that manifests as a regression on edge cases involving field type transitions combined with composite constraints.

## Solution Strategy

### 识别信号
- 观测到的现象: A crash/exception during migration execution, typically a constraint-not-found error (e.g., "Found wrong number (0) of constraints"), even though the auto-generated migration content appears correct in terms of the operations it contains. This is a **regression on edge cases** — it only surfaces when a field type change coincides with the field's participation in a composite constraint.

### 解决步骤
1. **Detect paired remove/add operations**: During auto-detection of migration operations, when generating an "add field" operation, check whether a "remove field" operation exists for the same model and field name within the same migration plan.
2. **Inject an explicit ordering dependency**: If such a removal exists, add an ordering dependency from the addition operation to the removal operation, ensuring the removal (and all operations that depend on the old field's existence, such as constraint drops) executes first.
3. **Make the dependency unconditional**: Apply this dependency check for **all** add-field operations, not just specific field type transitions. If no corresponding removal exists, the dependency is simply a no-op. This avoids brittle special-case detection logic.
4. **Validate the resulting dependency graph**: Verify that the final operation ordering is: (a) constraint removal → (b) old field removal → (c) new field addition. Ensure no cycles are introduced.

### Why This Works

The solution makes the implicit two-phase relationship between remove and add operations **explicit** in the dependency graph. By unconditionally checking for a paired removal when scheduling an addition, the system correctly handles replacement scenarios without needing to detect the specific field type transition that triggered the decomposition. The unconditional nature of the check is both safe (no-op when no removal exists) and general (covers all current and future field type transitions that decompose into remove/add pairs). This eliminates the ordering ambiguity that allowed the scheduler to interleave dependent operations incorrectly.

## Boundary Cases
- **No corresponding removal exists**: The dependency check finds nothing and is a no-op — no behavioral change for standard add-field operations.
- **Multiple constraints reference the old field**: All constraint-removal operations must be ordered before the field removal, which in turn must precede the field addition. The single dependency edge from add→remove is sufficient because constraint removals already depend on the field's existence.
- **Circular dependency risk**: If the add operation somehow depends on something that depends on the remove operation's output, a cycle could form. In practice, this does not occur because the add operation has no schema-state dependency on the removal — only an ordering requirement.
- **Cross-app field replacements**: If the remove and add operations land in different migration files (e.g., due to cross-app dependencies), the dependency must be expressed as an inter-migration dependency rather than an intra-migration ordering constraint.
- **Field rename vs. field replacement**: A rename is a single operation, not a decomposed remove/add pair. The unconditional check correctly ignores renames since no "remove field" operation is generated.

## PR Examples
- django__django-15738