## Problem Description

When an API accepts composite inputs (e.g., tuples of `(metadata, data)`) where the "data" slot is expected to hold a raw array or primitive payload, passing a **wrapper object** — one that carries both metadata and a lazy/chunked payload — into that raw-data position triggers an implicit type coercion. The wrapper's default conversion path (e.g., `.values` or `__array__`) eagerly materializes the underlying data, silently destroying lazy evaluation contracts such as Dask chunked computation. The result is silent data loss of the "laziness" property, unexpected memory spikes, and performance degradation during what should be lightweight, metadata-only operations.

This is a **leaky abstraction** problem: the coercion layer assumes every object in the data slot can be cheaply converted to a raw array, but wrapper objects violate that assumption because their default conversion has expensive or contract-breaking side effects.

## Root Cause Analysis

The root cause is an **implicit assumption violation** at the type-coercion boundary. APIs that accept structured composite inputs (tuples, dicts with structured values) funnel all data through a single unpacking/coercion chokepoint. This chokepoint treats the raw-data slot as "anything array-like" and applies a generic conversion (e.g., `np.asarray()`). When a wrapper object — which implements the array protocol but whose default materialization is eager — lands in that slot, the coercion silently triggers full computation.

The deeper principle: **semantic ambiguity at interface boundaries**. A wrapper object in the data position is ambiguous — does the caller intend to pass the wrapper's lazy payload (`.data`), its eagerly materialized values (`.values`), or the wrapper itself as a higher-level construct? The system resolves this ambiguity by picking one path silently, and the chosen path happens to be the most destructive one (eager materialization). Because no warning or error is raised, users have no signal that their lazy computation graph was just fully evaluated.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Lazy/chunked arrays (e.g., Dask arrays) silently become fully materialized NumPy arrays after passing through a constructor, update method, or factory function
  - Unexpected memory spikes or long computation delays during operations that should only touch metadata
  - Performance degradation that is disproportionate to the apparent complexity of the operation
  - Loss of chunking structure: objects that were chunked before an operation are no longer chunked afterward

### 解决步骤
1. **Map all API entry points** that accept composite structures (tuples, dicts) where one element is treated as raw data. Trace them to the single coercion/unpacking chokepoint through which all such inputs flow.
2. **Add an explicit type check** at the coercion chokepoint for wrapper objects (e.g., `Variable`, `DataArray`, or any type that carries both metadata and a lazy payload) appearing in the raw-data position.
3. **Emit a deprecation warning** rather than silently auto-extracting the payload. The warning should explain the ambiguity and guide users to explicitly extract the appropriate representation (e.g., `.data` for the lazy array, `.values` for the eager array).
4. **Plan a future hard error** (versioned deprecation timeline) that forces users to be explicit about their intent, eliminating the ambiguous code path entirely.
5. **Document the correct pattern**: when constructing from a composite input like `(dims, data)`, users should pass the raw lazy array directly (e.g., `obj.data`) rather than the wrapper object itself.

### Why This Works

Placing the check at the **single coercion chokepoint** ensures all call paths — constructors, update methods, factory functions — are covered without duplicating validation logic. The deprecation-then-error strategy is preferred over silent auto-fix because:

- **Auto-extracting the lazy payload could silently change behavior** if the wrapper's metadata (dimensions, coordinates, dtype) conflicts with the explicitly provided metadata in the composite input.
- **Making the ambiguity visible teaches users the correct mental model**: a wrapper object is not interchangeable with its payload, and the conversion has semantic consequences.
- **Gradual migration** via deprecation warnings avoids breaking existing code immediately while ensuring the ecosystem converges on the unambiguous pattern.

## Boundary Cases
- **Wrapper object whose lazy payload has no metadata conflicts**: auto-extraction would "work" but still masks the ambiguity; the deprecation warning should still fire to enforce explicitness.
- **Nested wrapper objects**: a wrapper containing another wrapper in its data slot — the coercion chokepoint must handle recursive unwrapping or reject it outright.
- **Non-lazy wrapper objects**: wrapper objects backed by in-memory NumPy arrays where materialization is cheap — the warning should still fire because the problem is semantic ambiguity, not just performance.
- **Third-party array types** (CuPy, Sparse, Pint) that implement `__array__` but have their own lazy or device-bound semantics — the type check must be extensible or protocol-based rather than hardcoded to specific types.
- **Dictionary-style updates** (e.g., `dataset.update({"var": (dims, wrapper_obj)})`) where the composite structure is implicit in the dict value — these must route through the same chokepoint.

## PR Examples
- **pydata__xarray-4493**: Identified that passing a `Variable` (wrapper with lazy Dask-backed data) into a tuple's raw-data slot caused silent eager materialization; solution added a deprecation warning at the coercion chokepoint to guide users toward explicit `.data` extraction.