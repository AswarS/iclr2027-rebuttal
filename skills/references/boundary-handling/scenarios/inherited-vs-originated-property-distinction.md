## Problem Description

When a system uses a single boolean flag (e.g., `auto_created`) to mark properties that were not explicitly defined by the developer, validation logic that relies on this flag can produce false positive warnings on child/derived entities. This occurs because the flag conflates two semantically distinct situations: (1) a property that was genuinely auto-generated with a default because no one configured it, and (2) a structural link property created by an inheritance/delegation mechanism that points back to a parent entity where the property *is* properly defined. The validation fires on every entity possessing the flagged property, rather than only on the entity that originates it.

## Root Cause Analysis

The underlying issue is that a single boolean flag is overloaded to represent multiple distinct semantic states. In frameworks that support model inheritance or delegation patterns, the mechanism that links a child entity to its parent reuses the same `auto_created` marker that is also used for genuinely defaulted fields. When a validation rule is introduced or tightened — checking "if this property is auto-created, warn the developer to configure it explicitly" — it cannot distinguish between "no one defined this anywhere" and "this exists because it was inherited from a parent that already has it configured." The validation predicate is necessary but not sufficient: it correctly identifies auto-created properties but over-broadly applies to inherited structural links, violating the principle that validation should fire at the point of origin, not at every point of possession.

This is an instance of the **implicit assumption violation** pattern: the original flag was introduced under the assumption that auto-creation had a single cause, and a later framework feature (inheritance) introduced a second cause without updating the flag's semantics or the downstream consumers that depend on it.

## Solution Strategy

### 识别信号
- 观测到的现象: False positive warnings or incorrect error messages appear on child/derived entities after a validation rule is introduced or tightened. The warnings reference a property that is correctly configured on the parent entity. The issue manifests as a **regression on edge cases** involving inheritance hierarchies — standalone entities validate correctly, but inherited entities produce spurious diagnostics.

### 解决步骤
1. **Audit all reasons a property can be marked as auto-created.** Enumerate the distinct code paths that set the flag: genuine default generation (no developer input) versus structural link creation (parent-link foreign keys, delegation pointers, etc.).
2. **Add a precondition to the validation check** that detects whether the auto-created property is a structural inheritance link (e.g., check if the field is a `parent_link` in Django's model inheritance). If it is, the property exists solely as a delegation mechanism and should not be validated on the child.
3. **Skip validation on the child entity for inherited structural links.** The child's possession of the property is a consequence of the parent's definition, not an independent omission.
4. **Ensure the parent entity still undergoes validation.** The warning must fire exactly once — at the entity that originates the property. If the parent has a genuinely unconfigured auto-created property, the warning should appear there and only there.
5. **Add comprehensive test coverage:**
   - (a) A parent entity with no explicit property configuration **triggers** the warning.
   - (b) A child entity inheriting from that parent does **not** trigger the warning.
   - (c) A parent entity with an explicitly configured property triggers **no** warning on either parent or child.
   - (d) Multi-level inheritance chains propagate the skip correctly.

### Why This Works

The fix restores the correct validation boundary by recognizing that inheritance creates a derived copy of a property, not an independent instance of it. By filtering out structural link properties from the validation predicate, the check targets only genuinely unowned auto-created properties. This aligns the validation with the semantic intent: "warn when no entity in the hierarchy has explicitly configured this property," rather than "warn on every entity that possesses an auto-created property." The principle is that **validation responsibility follows origination, not possession**.

## Boundary Cases
- **Multi-level inheritance (A → B → C):** The structural link check must work transitively. Entity C should not warn about a property originated in A, even through B.
- **Multiple inheritance / mixins:** When a child inherits from multiple parents, each parent link is structural; validation should only fire on the respective originating parent for each property.
- **Abstract base classes:** Abstract parents that define properties but are never instantiated directly — the first concrete child becomes the origination point and should be validated.
- **Proxy models:** Proxy models share the parent's database table and fields; they should not duplicate validation warnings from the concrete parent.
- **Explicit override on child:** If a child explicitly redefines a property (overriding the inherited one), the child becomes the new origination point and should be validated independently.

## PR Examples
- django__django-13925