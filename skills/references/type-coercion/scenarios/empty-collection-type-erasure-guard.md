## Problem Description

When a method transforms input data using internally stored typed state (e.g., a lookup table, sorted reference array, or mapping dictionary built during a fitting/training step), passing an empty collection as input can trigger a type mismatch crash. This occurs because languages and frameworks assign a default numeric type (typically `float64`) to empty arrays/collections, which may be incompatible with the non-numeric type (e.g., string, categorical) of the stored state. The bug is insidious because it only manifests when the fitted state holds certain types (e.g., strings) but works fine for others (e.g., integers), making it intermittent and easy to miss during testing.

## Root Cause Analysis

The underlying principle is an **implicit assumption violation**: developers assume that if an input passes structural validation (correct shape, correct container type, correct dimensionality), then downstream type-sensitive operations (comparisons, searches, casts) will succeed. However, type compatibility is **content-dependent** — it is inferred from the actual elements in the collection. An empty collection has no elements, so the framework falls back to a default type (e.g., `float64`). When the stored state expects a different type (e.g., object/string), operations like `np.searchsorted`, array concatenation, or dtype-based casting fail with a `TypeError` or `ValueError`.

This is a degenerate boundary case where the container exists but carries no content from which to infer a semantic type. The zero-element boundary is the exact point where "valid structure implies valid type" breaks down.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or `ValueError` during transform/inverse-transform on empty input
  - Crash occurs only when the model was fitted on non-numeric (e.g., string) data
  - The same empty input works fine when the model was fitted on numeric data
  - The error originates in a type-sensitive operation (search, comparison, cast) deep in the method, not at input validation

### 解决步骤
1. **Audit all methods that combine external input with internally stored typed state.** This includes both forward (transform) and inverse (inverse_transform) directions, as well as any predict or score methods that rely on fitted mappings.
2. **Add an early guard clause** at the top of each such method that checks whether the input has zero elements (e.g., `len(X) == 0` or `X.shape[0] == 0`).
3. **Short-circuit with an appropriately shaped empty result** before any type-sensitive operations are reached. The returned empty result should match the expected output shape and, where possible, the expected output dtype.
4. **Ensure input validation is symmetric** across all related methods. If one method validates dimensionality and shape, all sibling methods should apply the same checks — do not assume that only the "primary" method needs validation.
5. **Add explicit test cases** for empty inputs across all supported fitted data types (numeric, string, mixed/categorical) and for both forward and inverse operations.

### Why This Works

By short-circuiting before any type-sensitive operation, the empty-input guard eliminates the entire class of type-erasure mismatches at the zero-element boundary. The key insight is that an empty collection is semantically vacuous — there is no meaningful transformation to perform — so returning an empty result is both correct and safe. This avoids relying on downstream code to gracefully handle a dtype that was never intended to reach it. Applying the fix symmetrically across all code paths (forward, inverse, predict) prevents the same bug from hiding in less-tested sibling methods.

## Boundary Cases
- **Empty list `[]` vs. empty numpy array `np.array([])`**: Both may produce `float64` dtype by default, but they may enter different code paths depending on input validation logic. Both must be tested.
- **Empty 2D array `np.array([]).reshape(0, n_features)`**: The guard must handle both 1D and 2D empty inputs, preserving the correct output shape (e.g., `(0,)` vs. `(0, n_features)`).
- **Fitted on string data vs. integer data vs. mixed types**: The bug typically only manifests for non-numeric fitted types, so tests must cover all fitted dtype variants with empty input.
- **Inverse transform with empty input**: Often less tested than forward transform, but equally susceptible to the same type-erasure issue.
- **Multiple columns/features with heterogeneous types**: If the transformer handles multiple features independently (each with its own stored type), an empty input must correctly bypass all per-feature type-sensitive operations.

## PR Examples
- scikit-learn__scikit-learn-10508