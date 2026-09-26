## Problem Description

When code operates on objects through a polymorphic interface (e.g., normalization, transformation, or mapping abstractions), it may unconditionally invoke an operation—such as `inverse()`, `undo()`, or `decode()`—that is not guaranteed by all concrete implementations of that interface. Some implementations explicitly raise errors or lack support for the assumed operation, but the calling code provides no fallback path. The crash manifests only at runtime when a specific, less common implementation variant is used (e.g., a non-invertible normalization, a one-way transform, a lossy encoding), making it easy to miss during initial development and standard testing.

This is fundamentally a problem of **assuming interface uniformity**: treating all implementations as equally capable because the most commonly used ones happen to support the needed operation.

## Root Cause Analysis

Polymorphic interfaces often have a "common case" that supports a rich set of operations. Developers naturally write calling code against this common case, implicitly assuming all implementations share the same capabilities. When a less common or edge-case implementation lacks an optional operation (e.g., invertibility), the code crashes because:

1. **The interface contract is under-specified:** The abstract interface does not formally distinguish between universally required operations and optional/conditional ones.
2. **Testing bias toward common implementations:** Tests exercise the well-known, fully capable implementations, never triggering the missing-operation path.
3. **No capability negotiation:** The calling code has no mechanism to ask "can you do this?" before attempting the operation, nor does it provide a degraded-but-functional alternative.

The result is a latent runtime crash that only surfaces when a user supplies a capability-limited implementation—a classic regression-on-edge-case failure.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Runtime crash (e.g., `TypeError`, `NotImplementedError`, or domain-specific error) when a specific implementation variant is passed to otherwise generic code.
  - The exception originates from a method call on a polymorphic object (e.g., `norm.inverse(...)`) that works fine with the default/common implementation.
  - The failure is a regression or edge-case that only appears with non-standard configurations (e.g., `BoundaryNorm`, a non-invertible transform, a one-way codec).

### 解决步骤
1. **Audit the interface contract:** Enumerate all operations the calling code invokes on the polymorphic object. Classify each as universally supported vs. optional/conditional by reviewing all known concrete implementations. Identify which operations raise errors or are absent in certain variants.

2. **Introduce a capability check before the unsupported call:**
   - **Preferred:** Use an explicit type check (`isinstance`) or a capability flag (`obj.invertible`, `has_inverse`) to branch before invoking the optional operation. This preserves error visibility—genuine bugs in fully capable implementations still raise exceptions.
   - **Alternative:** Wrap the call in a `try-except` catching **only** the narrow, specific exception that signals the operation is unsupported (e.g., `ValueError` from a known non-invertible norm), never a broad `except Exception`.

3. **Implement a meaningful fallback** that achieves the caller's original goal using only data the limited implementation actually exposes. For example, if the goal is to determine precision/resolution and the inverse function is unavailable, derive it directly from the object's configuration data (boundary arrays, step sizes, quantization levels, etc.).

4. **Add a dedicated test case** that exercises the code path with a capability-limited implementation to prevent regression. Ensure the test verifies both that no exception is raised and that the fallback produces a correct/reasonable result.

### Why This Works

The fix explicitly acknowledges the capability gap in the interface rather than assuming uniformity. By checking capabilities before invocation and providing an alternative computation path:

- **Correctness is preserved:** The fallback uses data the limited implementation does expose, achieving the same functional goal through a different route.
- **Error visibility is maintained:** Using narrow checks (isinstance or specific exceptions) ensures that genuine bugs in fully capable implementations still surface as unhandled exceptions, rather than being silently swallowed by a broad try-except.
- **The interface contract becomes self-documenting:** The branching logic makes it explicit that certain operations are optional, guiding future maintainers.

## Boundary Cases
- **Implementations that partially support the operation** (e.g., inverse works for some input ranges but not others): The capability check must account for runtime conditions, not just static type.
- **New implementations added later** that also lack the operation: The fallback logic must be written generically enough (or the capability check must be based on a flag/protocol) to automatically cover future variants without code changes.
- **Fallback produces lower-fidelity results:** Document the degradation clearly so users understand behavior differences when using capability-limited implementations.
- **Chained or composed transformations** where only one link in the chain is non-invertible: The check must propagate through the composition, not just inspect the outermost object.

## PR Examples
- matplotlib__matplotlib-22835