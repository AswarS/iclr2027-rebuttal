## Problem Description

When an object's public accessor methods depend on internal state that is only materialized during a deferred lifecycle phase (e.g., rendering, layout pass, serialization), calling those accessors before that phase has executed results in `AttributeError` or equivalent crashes. The object's constructor leaves certain attributes uninitialized because their computation is expensive, context-dependent, or coupled to a later pipeline stage. However, the public API implicitly promises that accessors are callable at any time after construction, creating a hidden temporal coupling between internal lifecycle ordering and external API availability.

This is a **lifecycle-coupling-lazy-init** problem: the object's internal lifecycle stages are silently coupled to the availability of its public interface, and the absence of lazy initialization means the coupling is invisible until a user violates the assumed (but undocumented) call ordering.

## Root Cause Analysis

The fundamental cause is **lifecycle conflation** — developers who build the internal processing pipeline naturally think of the object's state as evolving through discrete stages (construct → configure → process → render → access results). They unconsciously assume that public accessors will only be called after the relevant stage has executed, because that is the order in which *they* exercise the code during development and testing.

This conflates two distinct contracts:
1. **Internal invariant**: "Attribute X exists after pipeline stage Y has run."
2. **External API contract**: "Method `get_x()` is callable on any validly-constructed instance."

Users, who have no knowledge of the internal pipeline, reasonably expect accessors to work immediately after construction. The mismatch between these two mental models is the root cause. The constructor creates a *structurally valid* object but a *semantically incomplete* one — it satisfies the language-level contract (the object exists) but not the API-level contract (all advertised methods work).

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `AttributeError` when calling a public getter or property on a freshly constructed object
  - Errors that disappear if an unrelated method (e.g., `draw()`, `render()`, `layout()`) is called first
  - Attributes that are only assigned as side effects inside internal pipeline methods, not in `__init__`
  - Test suites that always exercise the full lifecycle before querying state, masking the gap

### 解决步骤
1. **Audit all public accessors**: For every public method or property on the class, trace every attribute it reads back to its point of assignment. Verify that each attribute is either initialized in `__init__` or has a lazy-initialization guard in the accessor.
2. **Classify uninitialized attributes**: For each attribute that is only created during a deferred lifecycle phase, determine whether it can be cheaply initialized with a safe default (e.g., empty array, `None`, fallback color) or requires expensive/context-dependent computation.
3. **Apply the appropriate initialization strategy**:
   - **Cheap defaults**: Initialize directly in `__init__` with a semantically correct default value. Prefer this when the default is inexpensive and meaningful.
   - **Expensive/context-dependent**: Implement lazy initialization in the accessor — check for a sentinel value (e.g., `None`, a private flag) and trigger the deferred computation on demand. If the computation depends on external state (e.g., a parent container's transformation matrix), explicitly resolve that prerequisite inline before computing.
4. **Add pre-lifecycle accessor tests**: Write tests that call every public accessor immediately after construction, before any lifecycle methods (`draw`, `render`, `layout`, etc.) have been invoked. Assert that no `AttributeError` or crash occurs and that the returned value is a reasonable default or correctly computed result.
5. **Document lifecycle-dependent behavior**: If certain accessors intentionally return different results before vs. after a lifecycle phase, document this explicitly rather than leaving it as an implicit assumption.

### Why This Works

Lazy initialization decouples the public API contract from the internal execution order. It preserves the deferred computation design — avoiding premature or redundant work — while ensuring the public interface is always functional. The invariant shifts from "this attribute exists after stage X has run" to "this attribute is computed on first access if needed," which aligns the internal implementation with the external contract. Users no longer need hidden knowledge of the pipeline to use the object correctly.

## Boundary Cases
- **Circular lazy initialization**: The deferred computation for attribute A triggers computation of attribute B, which in turn requires A. Guard against infinite recursion with sentinel checks or explicit computation ordering.
- **Parent/context not yet available**: If lazy initialization depends on external state (e.g., a parent container) that genuinely does not exist yet, the accessor must either return a documented default or raise a clear, descriptive error — not an opaque `AttributeError`.
- **Thread safety**: If the object may be accessed from multiple threads, lazy initialization must be synchronized or made idempotent to avoid race conditions where two threads both detect the sentinel and compute simultaneously.
- **Stale cached state**: Once lazily initialized, the cached value may become stale if the underlying inputs change. Ensure that mutation of inputs invalidates the cached attribute (e.g., via dirty flags or property-based recomputation).
- **Serialization/pickling**: Lazily initialized attributes may or may not be present at serialization time. Ensure `__getstate__`/`__setstate__` or equivalent handles both cases correctly.

## PR Examples
- **matplotlib__matplotlib-23562**: A public accessor on a Matplotlib artist returned derived state (e.g., computed geometry) that was only populated during the `draw()` rendering pass. Calling the accessor before any rendering triggered an `AttributeError` on an attribute that was never assigned in `__init__`. The fix ensured the attribute was either initialized at construction or lazily computed on access.