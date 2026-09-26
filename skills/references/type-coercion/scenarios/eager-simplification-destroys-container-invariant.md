## Problem Description

When a composite/container data structure uses another eagerly-evaluating data structure internally to store its elements, the inner container's automatic simplification logic can collapse degenerate cases (e.g., a 1×1 matrix simplified to a scalar, a single-element list unwrapped to its bare value). This destroys the structural invariant that consumers of the outer container depend on — namely, that the internal storage always maintains a uniform type and dimensionality regardless of size. The result is a type error or crash when downstream code attempts uniform access (e.g., 2D indexing) on what has silently become a scalar or lower-dimensional object.

This pattern is insidious because it only manifests at boundary sizes (single-element, 1×1, empty) where simplification is most aggressive, while all "normal" sizes work perfectly. Developers naturally test with typical multi-element configurations and never encounter the degenerate collapse.

## Root Cause Analysis

The root cause is a **mismatch between two design intentions**: eager evaluation/simplification is an optimization designed for end-user-facing symbolic expressions, where collapsing a 1×1 matrix to a scalar is mathematically correct and ergonomically desirable. However, when that same eagerly-evaluating constructor is used as **internal structural storage** within another container, the simplification violates an implicit invariant — that the storage always has a consistent type and shape.

The underlying principle is that **structural containers used as implementation details must preserve their dimensionality unconditionally**, even when mathematically degenerate. The constructor's default behavior assumes it is producing a final result, not an intermediate structural component. When no flag is passed to suppress evaluation, the constructor applies its full simplification pipeline, and the degenerate case silently changes type — breaking the uniform interface contract that all consuming code relies upon.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or `AttributeError` when accessing elements of a container at boundary dimensions (1×1, single-element)
  - Errors like "object is not subscriptable" or "has no attribute `shape`" on what should be a matrix/array/container
  - The failure is **size-dependent**: identical code works for 2×2 but crashes for 1×1
  - Stack traces point to indexing or iteration over an internal storage object that has unexpectedly become a scalar or primitive type

### 解决步骤
1. **Locate the internal storage construction site**: Find where the outer container builds or populates its inner storage structure. Look for constructor calls to types known to have eager evaluation (e.g., `Matrix(...)`, `ImmutableMatrix(...)`, `Expr(...)`, or similar).
2. **Reproduce with the degenerate case**: Create a minimal test using the smallest possible dimensions (1×1, single element, empty) and exercise the full access path — construction, element retrieval via the uniform interface, and conversion back to the base type.
3. **Suppress eager evaluation at construction**: Pass a flag to disable simplification (e.g., `evaluate=False`), use a raw/literal constructor variant, or wrap the data in a non-simplifying container that preserves structural type unconditionally.
4. **Verify the structural invariant holds for all sizes**: Assert that `type(internal_storage)` and its dimensionality are identical whether the container holds 1 element or 100 elements.
5. **Add regression tests for boundary configurations**: Include tests for 1×1, 1×N, N×1, and empty cases that exercise construction → internal access → output conversion, ensuring the uniform interface is never broken.

### Why This Works

By suppressing eager evaluation at the internal storage construction site, we decouple the **structural role** of the container from the **simplification optimization** intended for end-user results. The inner container retains its type and shape invariant unconditionally, so all downstream code that assumes uniform dimensionality continues to work. The simplification can still be applied later, at the boundary where results are returned to the user — but never at the internal structural level where shape consistency is a hard requirement.

## Boundary Cases
- **1×1 matrix stored inside a block matrix**: The single-element inner matrix collapses to a scalar, breaking 2D indexing in the block matrix's element access methods.
- **Single-element symbolic collection**: A container wrapping one symbolic expression may unwrap it, causing iteration or length checks to fail.
- **Empty container**: Some constructors may return `None`, `0`, or a special sentinel instead of an empty container of the correct type, breaking downstream `.shape` or `.is_empty` checks.
- **Nested degenerate cases**: A 1×1 block inside a 1×1 block matrix — double simplification can compound the type mismatch.
- **Serialization/deserialization round-trip**: If the simplified form is serialized, reconstructing it may not restore the original structural type.

## PR Examples
- sympy__sympy-18621