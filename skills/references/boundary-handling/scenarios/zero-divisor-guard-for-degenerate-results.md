## Problem Description

This pattern occurs when a computation uses a result count (or a value derived from it) as a divisor or array-shape parameter, under the implicit assumption that the count is always positive. In practice, solvers, optimizers, or search routines can legitimately produce zero results under certain parameter configurations or degenerate input data (e.g., zero support vectors, zero selected features, zero active constraints). When the code attempts to divide by this count — typically to reshape a flat array into a structured output — it crashes with a `ZeroDivisionError` or produces malformed outputs. The problem is compounded when multiple code paths exist for different input representations (e.g., dense vs. sparse): one path may handle the zero case implicitly (e.g., by naturally producing an empty array), while the other performs explicit arithmetic that fails catastrophically.

## Root Cause Analysis

The underlying cause is an **implicit assumption violation** combined with a **symmetry-breaking bug** across parallel code paths.

1. **Implicit assumption violation**: The developer assumes that a solver or upstream computation will always produce at least one result. This is mathematically typical but not universally guaranteed. Hyperparameter choices (e.g., very strong regularization), degenerate data distributions, or edge-case configurations can drive the result count to zero. Division-based reshaping (e.g., `total_elements / n_classes` to determine rows) treats this count as a guaranteed-positive invariant, which it is not.

2. **Symmetry-breaking across code paths**: When two representations (dense and sparse) implement the same logical operation, one path may handle the empty case gracefully — for instance, sparse matrix slicing on an empty index set naturally yields an empty matrix — while the other path uses explicit index arithmetic (`array.reshape(n_results, -1)` or `total // n_results`) that is undefined at zero. The bug hides in the asymmetry: testing one path passes, while the other crashes.

3. **Cognitive trap**: The failure mode (`ZeroDivisionError`) is completely disconnected from the domain semantics (e.g., "the SVM found zero support vectors"), making diagnosis difficult without deep understanding of the upstream solver's behavior under edge conditions.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `ZeroDivisionError` or `ValueError` during array reshaping when a solver returns zero results
  - Crash occurs only for one input representation (e.g., dense) while the other (e.g., sparse) works fine on the same degenerate input
  - The failure is triggered by specific hyperparameter settings or edge-case data, not by typical usage
  - Regression on edge cases that previously worked or were never tested

### 解决步骤
1. **Audit all division and reshape operations** in the affected code path where a result count (or derived value) is used as a divisor or array-size denominator. Trace the variable back to its source to confirm it can be zero.
2. **Compare parallel code paths** for alternative input representations. If the equivalent path for sparse (or dense) input handles the zero case implicitly, document exactly what output it produces — this is the contract the other path must match.
3. **Add an explicit zero-guard** (`if result_count == 0:`) before the division. In the guarded branch, construct the appropriate empty/degenerate output structure directly (e.g., an empty array with the correct shape and dtype), matching the shape and type contract that downstream consumers expect.
4. **Verify semantic equivalence** between the two code paths for the degenerate case. Both paths should yield identical (or semantically equivalent) outputs when the result count is zero — same shape, same dtype, same downstream behavior.
5. **Add regression tests** with inputs specifically designed to provoke zero results from the solver (e.g., extreme regularization, single-sample classes, empty feature sets). Test both dense and sparse paths.

### Why This Works

The fix converts an implicit assumption ("result count > 0") into an explicit branch, handling the degenerate case with a well-defined output rather than undefined arithmetic. By using the already-working code path as a reference for the expected output contract, the fix ensures consistency across all representations. The guard is minimal and targeted — it does not alter the normal-case logic — and the regression test locks in the behavior so future refactors cannot reintroduce the asymmetry.

## Boundary Cases
- **Zero results from solver**: The primary case — e.g., zero support vectors, zero selected features, zero non-zero coefficients. The output should be an empty structure with correct shape (e.g., `(0, n_features)`).
- **Single-class or single-sample input**: May cause solvers to trivially converge with no meaningful results, triggering the same zero-count path.
- **Extreme hyperparameters**: Very high regularization, very low tolerance, or restrictive constraints that force the solver to select nothing.
- **Mixed dense/sparse input with identical degenerate data**: Both paths must produce equivalent outputs; testing only one representation is insufficient.
- **Downstream consumers of the empty output**: Operations like concatenation, stacking, or iteration over the result must handle empty arrays gracefully — verify that the shape contract is sufficient for all consumers.

## PR Examples
- scikit-learn__scikit-learn-14894