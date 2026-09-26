## Problem Description

When a domain-specific type system defines specialized "zero" or "identity" values that carry metadata (e.g., shape, dimensions, units, coordinate frames) beyond their algebraic value, the underlying symbolic algebra engine's simplification rules can silently strip that metadata. Generic rewrite rules like `0 + 0 → 0` produce a plain scalar zero that lacks the required domain context. This type degradation is insidious because it often only manifests after multiple chained operations: the first pass produces a valid typed result, but internal simplification reduces it to a bare scalar, and subsequent operations crash when they attempt to access metadata that no longer exists on the degraded value.

## Root Cause Analysis

The fundamental issue is a **type-system boundary mismatch**: the symbolic algebra engine operates on a generic expression tree and applies universal algebraic identities without awareness of domain-specific subtypes. When two domain-typed zeros are combined (e.g., a zero vector plus a zero vector), the engine sees `0 + 0` and collapses it to a plain `S.Zero` — a scalar with no shape, dimension, or other metadata. This plain zero then gets stored as an intermediate sub-expression within a domain object. On the next operation that inspects or iterates over sub-expressions, code expects every component to be a domain-typed value (or at least carry the expected metadata interface), but instead encounters a raw scalar. The result is a `TypeError`, `AttributeError`, or similar crash.

The key cognitive trap is the assumption that operations between domain-typed values always yield domain-typed results. In practice, the symbolic engine's own canonicalization rules can "escape" the domain type hierarchy at any point, and this escape is only visible when the degraded value is consumed downstream — often several operations later.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or `AttributeError` when accessing domain-specific metadata (e.g., `.components`, `.shape`, `.frame`) on what should be a domain-typed value but is actually a plain scalar zero.
  - The failure is **non-deterministic by depth**: a single operation succeeds, but chaining the same operation two or three times triggers the crash.
  - Stack traces point to generic arithmetic or simplification internals producing `S.Zero` where a typed zero was expected.
  - The bug appears in data-transformation or metadata-processing code paths, not in the core algebra itself.

### 解决步骤
1. **Locate the base class** of the domain-specific type hierarchy — this is where the type boundary with the symbolic engine is thinnest and where the fix has maximum coverage. Do not patch individual downstream consumers.
2. **Identify the method or property** where sub-expressions are accessed, returned, or propagated outward (e.g., a `.components` property, an `__iter__` method, or a normalization/simplification hook). Trace the code path where a plain scalar zero could slip through without conversion.
3. **Add a small guard** (typically ~2 lines) that checks whether a returned or propagated value is the plain scalar zero (`S.Zero` or equivalent) and, if so, converts it to the domain-typed zero with appropriate metadata inferred from context (e.g., the expected dimensions, shape, or coordinate frame at that position).
4. **Ensure the guard is positioned at the source of propagation** — the moment a value exits the symbolic engine and re-enters the domain type system — so that no downstream code ever encounters the untyped scalar.
5. **Add regression tests** that chain the relevant operation at least three times with zero-valued components, verifying both correctness of the result and preservation of the domain type at each intermediate step.

### Why This Works

By placing the guard at the base class level — the exact boundary where the symbolic engine's output re-enters the domain type system — we intercept type degradation at its source. This follows the principle of **correcting corruption at the point of origin**: the moment a scalar zero would be returned where a domain-typed zero is expected, it is converted, so no downstream code ever encounters the inconsistency. This is both minimal (a small, localized change) and comprehensive (it covers all code paths that flow through the base class).

## Boundary Cases
- **Non-zero simplifications that lose type**: The same pattern can occur with other identity elements (e.g., a scalar `1` replacing a typed identity matrix). The guard logic should be reviewed for all algebraic identity values, not just zero.
- **Nested or recursive domain types**: If domain-typed values can contain other domain-typed values (e.g., a matrix of vectors), the guard must handle type preservation at each nesting level, not just the outermost.
- **Multiple metadata dimensions**: When the domain type carries several independent pieces of metadata (e.g., both a coordinate frame and a dimension), the guard must reconstruct all of them, not just one.
- **Performance on hot paths**: If the guarded method is called in tight loops (e.g., during large symbolic simplifications), the isinstance check should be as lightweight as possible — prefer identity comparison (`expr is S.Zero`) over general type checks where applicable.

## PR Examples
- sympy__sympy-17630