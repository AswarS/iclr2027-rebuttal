## Problem Description

When a code generator, migration autodetector, or similar tool temporarily restores an object's internal state to simulate a prior version (e.g., to serialize what a field "used to look like" before a rename), it must restore **all** interrelated attributes that the serialization/deconstruction logic consults together. If only a subset of co-dependent attributes is rolled back, the object enters an internally inconsistent state during serialization, causing conditional logic to evaluate against mismatched data and produce incorrect output — such as stale parameter values, missing arguments, or spurious extra arguments in the generated code.

This is a **partial-propagation** problem within **state-synchronization**: the system correctly identifies that one attribute changed and adjusts it, but fails to propagate that adjustment to sibling attributes that form a logical unit with it.

## Root Cause Analysis

Serialization and deconstruction methods frequently contain conditional logic that derives output decisions from the **relationship between multiple attributes**, not from any single attribute in isolation. For example, a ForeignKey's `deconstruct()` may check whether the referenced field is the primary key of the referenced model — a check that requires both the model reference and the field name to be consistent with each other.

When a tool (such as a migration autodetector) temporarily patches one attribute to simulate a previous state (e.g., reverting a field name to its pre-rename value), but leaves the companion attribute pointing at the current state (e.g., the model reference still resolves to the already-renamed model), the conditional check operates on a **cross-temporal mismatch**: one attribute reflects the old state while the other reflects the new state. This mismatch causes the conditional to take the wrong branch, producing serialized output that is silently incorrect.

The cognitive trap is **treating a multi-attribute consistency requirement as a single-attribute update problem**. Developers naturally focus on the attribute that directly changed and overlook that the serialization logic also consults sibling attributes to make its decisions. The invariant that these attributes must form a consistent snapshot is implicit and easy to miss.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: Generated migration scripts or serialized representations contain stale, incorrect, or unexpected parameter values (e.g., an explicit `to_field="id"` that should have been omitted, or a reference to a field name that no longer exists).
  - **Inconsistent state**: During temporary state restoration for comparison or serialization, an object's attributes reference entities from different points in time, causing conditional logic to evaluate incorrectly.
  - The bug is typically **silent** — no exception is raised; the output simply contains wrong values that may cause failures downstream (e.g., when applying the generated migration).

### 解决步骤
1. **Map the attribute dependency graph for serialization**: Identify all attributes that the `deconstruct()` or equivalent serialization method consults together to make conditional decisions. Document which attributes form logical groups that must be consistent with each other (e.g., a target model reference + a target field name within that model).

2. **Trace all temporary state adjustment sites**: Find every code path where one or more attributes are temporarily modified to simulate a prior state (e.g., in a migration autodetector's rename handling). For each site, verify that **all** co-dependent attributes in the logical group are adjusted together, not just the one that was directly renamed or changed.

3. **Restore the full consistent snapshot**: When adjusting one attribute of a reference (e.g., the target field name), also adjust every companion attribute (e.g., the target model/container reference) so that the serialization logic sees a coherent, self-consistent state. This may mean temporarily swapping in the old model instance or old related object, not just the old name string.

4. **Add regression tests**: Create a test that performs the triggering operation (e.g., renaming a referenced field) and then verifies that the generated serialization output does not contain stale references to the old name, does not include parameters that should be omitted, and matches the expected canonical form.

### Why This Works

By ensuring that all attributes forming a logical consistency group are restored together, the serialization method's conditional logic evaluates against a coherent snapshot — either entirely the old state or entirely the new state — rather than a hybrid. This eliminates the cross-temporal mismatch that causes wrong-branch evaluation. The principle is **atomic state restoration**: when simulating a prior version of an object, the simulation must be complete with respect to every attribute the consumer (serialization logic) will inspect.

## Boundary Cases

- **Chained renames**: If both the field name and the model name are renamed in the same migration, the temporary restoration must account for both renames simultaneously, not sequentially, to avoid intermediate inconsistent states.
- **Self-referential models**: A ForeignKey pointing to `"self"` may have different resolution behavior; the companion attribute adjustment must handle the case where the model reference is symbolic rather than a concrete object.
- **Multiple fields referencing the same target**: When a renamed field is referenced by several other fields (e.g., multiple ForeignKeys with explicit `to_field`), every referencing field's state must be adjusted, not just the first one discovered.
- **Inherited fields**: If the renamed field is inherited from a parent model, the attribute that resolves the "owning model" may differ from the attribute that resolves the "concrete model," and both may need adjustment.
- **No-op detection**: If the old and new states happen to produce the same serialization output (e.g., the referenced field is still the primary key after rename), the bug may be masked in simple test cases — tests should cover scenarios where the conditional output genuinely diverges.

## PR Examples

- **django__django-11910**: Migration autodetector partially restored a ForeignKey's `to_field` attribute to simulate the pre-rename state but did not also restore the companion `related_model` reference. This caused `deconstruct()` to incorrectly include an explicit `to_field` parameter in the generated migration because its "is this the primary key?" check compared the old field name against the new (already-renamed) model, finding no match.