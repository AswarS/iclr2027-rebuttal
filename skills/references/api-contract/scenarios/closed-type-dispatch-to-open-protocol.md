## Problem Description

A dispatch chain that renders or formats objects handles a fixed set of known types (e.g., NumPy arrays, sparse arrays, dask arrays) with specialized branches and falls through to a generic handler for everything else. Third-party or plugin types that carry contextual information—such as units, metadata, or abbreviated summaries—lose that information when the generic fallback applies a plain `__repr__` or `str()` conversion that receives no contextual parameters (like available display width). The dispatch chain implicitly assumes a **closed world** of types, making it impossible for new types to opt into richer, context-aware formatting without modifying the host library's source code.

## Root Cause Analysis

The underlying principle violated is the **closed-world assumption in type dispatch chains**. When developers enumerate the types they know about at design time and treat a generic fallback as universally adequate, they implicitly close the set of types that can participate in context-sensitive behavior. A plain `__repr__` or `__str__` method cannot accept contextual parameters (available width, nesting depth, display mode) that the formatting system already has in hand. As the ecosystem grows—custom array backends, unit-aware arrays, provenance-tracking wrappers—the generic fallback becomes a lossy bottleneck that strips away exactly the information these types exist to carry. The fix requires treating the set of representable types as **open** by introducing a duck-typing protocol that any type can implement to opt in, without subclassing or registration.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Custom or third-party array-like objects display as raw, unhelpful `repr` strings in summaries, losing units, metadata, or other domain-specific context.
  - The formatting output is technically correct but semantically incomplete—a **partial-result** or **wrong-output** failure where important information is silently discarded.
  - Users or library authors file issues requesting a way to customize inline representation for their types.
  - The dispatch chain contains an `if/elif/.../else` structure (or equivalent) where the `else` branch applies a context-free string conversion.

### 解决步骤
1. **Trace the dispatch chain end-to-end.** Starting from the top-level display or summary function, follow the control flow through each type-specific branch down to the generic fallback. Document what contextual parameters (e.g., `max_width`, nesting depth) are available at the dispatch site but not passed to the fallback.
2. **Define a duck-typing protocol method.** Choose a clearly namespaced method name (e.g., `_repr_inline_(max_width)`) that custom types can implement. The method signature must accept the contextual parameters the formatting system already possesses. Document the protocol's contract: input parameters, expected return type, and behavioral expectations (e.g., "return a string no wider than `max_width` characters").
3. **Insert a protocol-check branch in the dispatch chain.** Use `hasattr` or an equivalent duck-typing check to detect whether the underlying data object implements the protocol method. Place this branch **after** all established special-case handlers for well-known types (whose behavior is stable and tested) but **before** the generic fallback.
4. **Delegate to the protocol method when present.** When the check succeeds, call the protocol method with the appropriate contextual parameters and use its return value directly, bypassing the generic fallback entirely.
5. **Preserve the generic fallback unchanged.** Objects that do not implement the protocol method must continue to receive exactly the same treatment as before—no behavioral regression for existing types.
6. **Add comprehensive tests covering three axes:**
   - **(a) Opt-in works:** An object implementing the protocol method gets its custom representation used in the summary output.
   - **(b) Opt-out is safe:** An object without the protocol method falls through to the generic handler and produces identical output to the pre-change behavior.
   - **(c) Established types are unaffected:** All pre-existing special-case branches (e.g., for dask, sparse) continue to match first and produce unchanged output, confirming the new branch does not shadow them.

### Why This Works

Duck-typing protocols are the idiomatic extension point in dynamically-typed ecosystems. They allow third-party types to opt in to richer behavior without subclassing, registration, or coupling to the host library's internals. By placing the protocol check after known-type branches but before the generic fallback, the solution respects the **open-closed principle**: the dispatch chain is open for extension (any new type can implement the method) but closed for modification of existing behavior (no established branch is reordered or altered). The contextual parameters passed through the protocol method close the information gap that made the generic fallback lossy in the first place.

## Boundary Cases

- **Protocol method returns a value exceeding the requested width.** The caller should either truncate gracefully or document that the protocol method is responsible for honoring the width contract. Decide and document which side owns truncation.
- **Object implements the protocol method but raises an exception.** The dispatch chain should decide whether to catch the error and fall back to the generic handler (resilient but potentially confusing) or let it propagate (strict but debuggable). A warning-and-fallback strategy is often the safest default.
- **Subclass of a known special-case type also implements the protocol method.** The special-case branch will match first by design, so the protocol method is never called. Document this precedence clearly so that subclass authors know to override the special-case path if they need custom behavior.
- **Protocol method name collides with an existing method on a third-party type.** Use a sufficiently distinctive, namespaced name (e.g., prefixed with `_repr_`) to minimize collision risk. Consider checking the method's signature or return type as an additional guard.
- **Multiple layers of wrapping** (e.g., a unit-aware array wrapping a dask array). The outermost wrapper's protocol method is what the dispatch chain sees; it is responsible for composing inner representations if needed.

## PR Examples

- **pydata__xarray-4248**: Introduced a `_repr_inline_` duck-typing protocol method so that custom array types (e.g., unit-aware arrays from `pint-xarray`) can control their inline representation in xarray's dataset/variable summaries, inserted as a new dispatch branch before the generic `format_array_flat` fallback.