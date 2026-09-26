## Problem Description

When mathematical decompositions (eigendecomposition, SVD, or similar matrix factorizations) produce basis vectors, components, or embeddings, the results carry inherent sign ambiguity — if **v** is a valid eigenvector, then **−v** is equally valid. Numerical solvers make no guarantee about which sign orientation they return, leading to outputs that are identical in magnitude but may differ in sign across repeated runs on the same data. This non-determinism manifests as inconsistent embeddings, flipped components, or irreproducible transformations, even when the random seed is fixed and the input data is unchanged.

## Root Cause Analysis

Eigenvectors and singular vectors are mathematically defined only up to a sign (or phase) factor. The specific sign returned by a numerical solver depends on internal iteration details — convergence paths, floating-point accumulation order, LAPACK/BLAS implementation specifics, parallelism-induced reordering of operations, and platform-level differences. None of these are controlled by the user-facing random seed.

The core cognitive trap is the assumption that **deterministic input + fixed random seed = reproducible decomposition output**. This is false because the sign ambiguity is not a randomness problem — it is a mathematical degeneracy in the solution space. The solver is free to return any valid sign orientation, and subtle environmental differences silently flip signs without affecting mathematical correctness. Without an explicit post-hoc canonicalization step, the output is inherently unstable.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Repeated runs on identical data produce results that match in absolute value but differ in sign for one or more components.
  - Tests comparing `.transform()` or `.fit_transform()` outputs across invocations fail intermittently with sign-flipped columns/rows.
  - Cross-platform CI pipelines show inconsistent results for decomposition-based methods.
  - Users report non-reproducible embeddings or components despite using the same random state and data.

### 解决步骤
1. **Audit all decomposition steps** in the pipeline that produce outputs with inherent sign ambiguity — eigendecompositions, singular value decompositions, spectral embeddings, and related factorizations.
2. **Apply a deterministic sign-flipping convention immediately after the decomposition**: for each component vector, choose the sign such that the element with the largest absolute value is positive. This is a well-established canonical rule (sometimes called the "max-abs" convention).
3. **Reuse existing sign-normalization utilities** if the codebase already provides one (e.g., `svd_flip` in scikit-learn). This ensures consistency across all factorization-based transformations and avoids duplicating logic.
4. **Apply the convention before any subsequent reordering** (e.g., sorting by eigenvalue magnitude or variance explained), so the canonical form is established on the raw decomposition output and is not disrupted by downstream permutations.
5. **Handle API mismatches gracefully**: when the normalization utility expects multiple matrix arguments (e.g., both U and V from SVD) but only one is relevant in the current context, pass a placeholder (e.g., an empty array with matching shape) for the unused argument and discard its returned result.
6. **Add regression tests** that verify bitwise-identical output across multiple invocations of `fit_transform` on the same input data, explicitly catching sign instability.

### Why This Works

The max-abs sign convention imposes a unique canonical form on each component vector by anchoring its orientation to an objective, solver-independent property of the vector itself (the position and sign of its largest-magnitude element). This eliminates the degeneracy at its source: regardless of which sign the solver happened to choose, the post-hoc flip always maps the result to the same canonical orientation. The convention is invariant to platform, parallelism, library version, and convergence path — the only requirement is that the decomposition is non-degenerate (no ties in the largest absolute value, which is generic for real-world data).

## Boundary Cases

- **Degenerate eigenvalues**: When two or more eigenvalues are equal (or nearly equal), the corresponding eigenvectors span a subspace and can be arbitrarily rotated within it. Sign-flipping alone does not fully resolve this ambiguity; additional subspace alignment may be needed.
- **Tied max-abs elements**: If two elements in a component vector share the same largest absolute value but differ in sign, the convention becomes ambiguous. In practice this is vanishingly rare with real-valued data, but a tiebreaking rule (e.g., prefer the earlier index) should be specified.
- **Complex-valued decompositions**: The ambiguity generalizes from sign to arbitrary phase (multiplication by e^{iθ}). The max-abs convention extends naturally by rotating the phase so the largest element is real and positive.
- **Sparse or structured inputs**: When the decomposition operates on a sparse matrix or graph Laplacian, ensure the sign-flip utility handles sparse representations without densifying unnecessarily.
- **Downstream consumers of both U and V**: In full SVD contexts where both left and right singular vectors are used, the sign flip must be applied consistently to both matrices (flipping a column of U requires the corresponding row of V to be flipped as well) to preserve the factorization identity.

## PR Examples

- **scikit-learn__scikit-learn-13241**: Spectral embedding produced non-deterministic sign orientations across runs. Fixed by applying `svd_flip`-style sign canonicalization to eigenvectors immediately after the eigendecomposition step, ensuring reproducible embeddings.