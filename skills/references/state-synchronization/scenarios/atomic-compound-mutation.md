## Problem Description

When a class manages a pair of semantically coupled values (e.g., min/max boundaries, lower/upper limits), and its internal logic triggers validation, transformation, or observer callbacks after each individual property assignment, a compound update that modifies both values sequentially creates a transient inconsistent state. The validation or processing that fires after the first assignment sees one updated value paired with a stale or null counterpart, violating invariants that require both values to be valid and mutually consistent. This commonly manifests as a regression when a subclass introduces stricter validation (e.g., both values must be positive and non-null) over code that previously assigned the values one at a time without issue.

## Root Cause Analysis

The fundamental issue is treating semantically coupled properties as independently settable values when the class's invariants apply to the pair as a unit. When each property setter eagerly triggers validation or observer notification, the class implicitly assumes that every individual assignment leaves the object in a fully valid state. However, compound mutations — where both values must change together to transition from one valid state to another — necessarily pass through an intermediate state where only one value has been updated. If any validation, transformation, or callback fires during this intermediate state, it encounters an inconsistent pair and fails.

This is an instance of **invariant erosion**: the original sequential assignment pattern was safe under the base class's lenient validation, but a subclass or later refactoring introduced stricter invariants that the intermediate state cannot satisfy. The coupling between the two values is a design-level fact, but the update mechanism does not respect it.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - An exception (crash) occurs inside a validation, normalization, or observer callback during what should be a routine update of boundary values.
  - The traceback shows the error originates from processing that expects both values to be valid, but one is `None`, stale, or otherwise inconsistent with the other.
  - The failure is triggered by a compound operation (e.g., setting both `vmin` and `vmax`), not by setting a single value in isolation.
  - The bug is a regression — it appeared after a subclass added stricter validation or eager processing that did not previously exist.
  - External workarounds (e.g., suppressing callbacks at every call site) are fragile and incomplete.

### 解决步骤
1. **Trace the exception to the premature validation point.** Follow the traceback to identify the exact location where validation or processing fires on a partially-updated pair of coupled values. Confirm that the error is caused by one value being updated while the other remains in its prior (invalid or stale) state.
2. **Identify the compound update code path.** Locate the method or sequence of property assignments that updates both values. Verify that each individual setter triggers validation or callbacks independently, creating the transient inconsistent window.
3. **Introduce a deferred-validation mechanism inside the class.** Modify the class's internal update logic so that when both values are being changed together, validation and observer notification are deferred until both assignments are complete. This can be implemented as:
   - A guard flag (e.g., `_updating`) that suppresses validation during the compound update.
   - A bulk-set method that accepts both values, assigns them internally, and then triggers validation once.
   - Restructuring the assignment to write both raw values before invoking any derived computation.
4. **Ensure validation fires exactly once after both values are consistent.** After both values reach their final state, trigger the full validation/processing/notification pipeline. This preserves all existing observer contracts while eliminating the intermediate invalid state.
5. **Fix at the source, not at call sites.** The fix belongs inside the class's own value-setting logic — where the coupling between the two values is defined — not in every external caller. This ensures all code paths that perform compound updates are protected.
6. **Add a regression test.** Create a test that sets up the class (including any strict-validation subclass) with observers attached, performs the compound update, and verifies that no exception is raised and the final state is fully consistent.

### Why This Works

The class's invariants are defined over the pair of values, not over each value individually. By deferring validation until both values are assigned, the update mechanism respects the atomicity of the state transition: the object moves directly from one valid state to another without exposing an intermediate inconsistent state to any observer or validation logic. This aligns the implementation with the semantic reality that the two values are coupled and must be treated as a single logical unit during mutation.

## Boundary Cases
- **Only one value changes:** When a single property is updated in isolation, the other value is already in a valid state, so immediate validation is correct and should not be suppressed.
- **Recursive or re-entrant updates:** If an observer callback itself triggers another compound update, the deferred-validation mechanism must handle re-entrancy without skipping validation for the outer update or deadlocking on the guard flag.
- **One or both values set to `None` or sentinel:** Some classes allow `None` as a "not yet set" marker. The deferred validation must distinguish between a transient `None` during a compound update and a legitimate `None` that should be validated.
- **Subclass-specific invariants beyond non-null:** Subclasses may enforce ordering (`vmin < vmax`), sign constraints (both positive for log scales), or type constraints. The deferred validation must still run the full subclass validation chain after both values are set.
- **Serialization / deserialization round-trips:** Restoring state from a serialized form may set values one at a time; the bulk-set or guard mechanism should be used in deserialization paths as well.

## PR Examples
- matplotlib__matplotlib-25079