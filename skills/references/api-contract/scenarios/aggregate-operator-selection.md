## Problem Description

This pattern occurs when a function computes an aggregate property from a collection of component values and uses an incorrect reduction operator (e.g., `max` instead of `sum`). The bug is insidious because the wrong operator produces correct results for degenerate inputs where only one component is non-zero — causing tests to pass while the implementation silently violates its documented contract. The error surfaces only when inputs distribute values across multiple components, such that no single component equals the expected aggregate.

A canonical example: "total degree" of a polynomial is defined as the **sum** of exponents across all variables, but an implementation mistakenly uses `max` over the exponents. For a monomial like `x³` (exponents: 3,0,0), both `sum` and `max` yield 3. But for `x·y·z` (exponents: 1,1,1), `sum` correctly yields 3 while `max` incorrectly yields 1.

## Root Cause Analysis

The underlying cause is **operator confusion in reductions over collections**. Sum, max, min, count, any, and all are all valid aggregation operators, but they encode fundamentally different semantics. When a specification defines an aggregate as a "total" (implying summation), substituting `max` or another operator creates a contract violation that is invisible in degenerate cases.

The cognitive trap is **anchoring on degenerate test inputs**. Developers naturally test with the simplest cases first — single-variable polynomials, single-item collections, single-contributor scores. In these cases, the dominant (and only non-zero) element equals the sum, so `max == sum`. The developer's mental model collapses the distinction between "the largest part" and "the whole," and the divergence only manifests when the value is genuinely distributed across multiple parts. This creates a false sense of correctness that can persist through code review and initial test suites.

## Solution Strategy

### 识别信号
- 观测到的现象: **Partial or wrong results** — the function returns correct values for simple/pure inputs (single-variable, single-item) but incorrect values for composite/distributed inputs (multi-variable, multi-item). Filtering or threshold checks based on the aggregate silently exclude or include wrong elements. Tests pass for degenerate cases but fail when multi-component inputs are introduced.

### 解决步骤
1. **Audit all aggregate computations**: Identify every location where a collection of component values is reduced to a single scalar (e.g., iterating over a dictionary of parts and applying a reduction). Search for `max()`, `min()`, `any()`, `all()` calls over component collections.
2. **Cross-reference against the specification**: For each aggregate, verify the reduction operator matches the **documented or mathematically defined** semantics. If the contract says "total degree," confirm the code uses `sum`, not `max`. If it says "minimum cost," confirm `min`, not `sum`.
3. **Construct distributed test cases**: Write tests where the aggregate value is spread across multiple components such that no single component equals the expected aggregate. For example, if testing total degree 3, use inputs like `(1,1,1)` and `(1,2,0)`, not just `(3,0,0)` or `(0,0,3)`.
4. **Replace the incorrect operator**: Swap the wrong reduction for the correct one as defined by the specification.
5. **Check for duplicated logic paths**: Verify the fix in all code branches where the logic may be duplicated — e.g., commutative vs. non-commutative handling, cached vs. computed paths, or multiple filter/threshold conditions that reference the same aggregate.

### Why This Works

The fix aligns the programmatic reduction operator with the mathematical or contractual definition of the aggregate property. By testing with distributed inputs — where the various reduction operators provably diverge — we break the degeneracy that masked the bug. The principle is simple: **always verify that the reduction semantics match the specification, and always test with inputs where candidate operators produce different results**.

## Boundary Cases
- **Single-component inputs (degenerate case)**: All common reduction operators (`sum`, `max`, `min`) coincide when only one element is non-zero. These cases will pass regardless of which operator is used and therefore cannot detect this bug — they must be supplemented with multi-component tests.
- **Zero or empty collections**: An empty collection may cause `max()` or `min()` to raise exceptions while `sum()` returns 0. Ensure the chosen operator handles the empty case correctly per the contract.
- **Negative component values**: `sum` and `max` diverge dramatically when negative values are present (e.g., components `[3, -1]` yield sum=2 but max=3). If the domain permits negative values, this is another axis of divergence to test.
- **All-equal components**: Inputs like `(2,2,2)` where sum=6 but max=2 provide strong discriminating power between operators and should be included in test suites.
- **Duplicated or branching logic**: The same aggregate may be computed in multiple code paths (e.g., fast-path vs. general-path, or type-specific branches). Each path must be independently verified.

## PR Examples
- sympy__sympy-21847