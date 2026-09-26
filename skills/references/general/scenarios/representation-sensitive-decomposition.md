## Problem Description

This pattern occurs when a predicate or property query on a composite symbolic expression (e.g., "is this product an integer?", "is this expression positive?") delegates to a global decomposition or normalization utility that is sensitive to the internal tree structure of the expression, rather than its mathematical meaning. Because the same mathematical expression can have multiple valid internal representations—depending on whether it was constructed with eager evaluation, passed through simplification, or assembled in a particular argument order—the decomposition utility may produce different outputs for semantically equivalent inputs. This causes the predicate to return inconsistent, indeterminate, or outright incorrect results depending on the construction path.

The core issue is a **symmetry break**: the predicate's correctness depends on a representation invariant that the system does not actually guarantee.

## Root Cause Analysis

Global decomposition utilities (such as fraction extraction, polynomial factoring, or canonical numerator/denominator splitting) are designed to operate on expressions in a normalized or fully-evaluated form. They implicitly assume that the input's syntactic tree structure corresponds to a canonical representation of its mathematical content. However, symbolic computation systems routinely produce structurally different but mathematically equivalent internal forms through:

- **Unevaluated construction** (e.g., `Mul(a, b, evaluate=False)` vs. `a * b`)
- **Different argument orderings** or groupings
- **Partial simplification** at intermediate stages

When a predicate calls a global decomposition on such a non-canonical form, the decomposition may misidentify components (e.g., failing to extract the correct denominator, or misclassifying a factor's parity). The predicate then reasons from this incorrect decomposition and returns a wrong answer.

The cognitive trap is **assuming representation invariance** of utility functions—believing that a decomposition utility always produces the same mathematical result regardless of the input's internal tree structure. In practice, many such utilities are only correct on fully-evaluated expressions, making any predicate that must handle both evaluated and unevaluated forms vulnerable.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - The same mathematical expression yields **different predicate results** (e.g., `True` vs. `None`, or `True` vs. `False`) when constructed via different code paths.
  - Downstream reasoning or simplification **diverges** for equivalent expressions (inconsistent state).
  - The predicate works correctly on "simple" or fully-evaluated forms but fails on unevaluated, reordered, or partially-simplified variants.
  - A global decomposition utility (e.g., `as_numer_denom()`, `as_coeff_Mul()`, `as_independent()`) is called on the entire composite expression inside the predicate implementation.

### 解决步骤
1. **Reproduce the inconsistency**: Construct the same expression via at least two different paths (evaluated vs. unevaluated, different argument orders) and compare the predicate output. Confirm they differ.
2. **Trace to the decomposition call**: Follow the predicate implementation to find where it invokes a global decomposition or normalization utility on the full composite expression.
3. **Confirm representation sensitivity**: Feed the structurally different but semantically equivalent inputs into the decomposition utility directly and verify it produces different outputs. This pinpoints the root cause.
4. **Replace global decomposition with per-component analysis**: Instead of decomposing the entire expression at once, iterate over individual sub-expressions (e.g., factors of a product, terms of a sum) and classify each one locally using stable, intrinsic properties—type checks, parity, sign, known integer status—that do not depend on the surrounding expression's syntactic form.
5. **Compose results soundly**: Accumulate per-component classifications and derive the predicate result through compositional reasoning (e.g., for "is this product an integer?", use odd/even parity analysis of factors; for "is this sum rational?", check each term individually).
6. **Handle unresolvable cases explicitly**: When local analysis cannot determine a component's classification, return an explicit "unknown" (`None`) rather than guessing or defaulting to an incorrect definite answer.
7. **Add regression tests**: Create tests that construct the same expression via both evaluated and unevaluated paths and assert identical predicate results. Include edge cases with mixed numeric and symbolic factors.

### Why This Works

Per-argument analysis is **representation-invariant** by construction: each argument's local properties (whether it is an integer, whether it is even, its sign) are intrinsic to that sub-expression and do not change based on how the parent expression's tree is structured. By never asking a global utility to decompose the full expression—where the syntactic grouping can mislead—the predicate avoids the representation-sensitivity entirely. Compositional reasoning over stable local facts produces consistent results regardless of construction path.

## Boundary Cases

- **Nested unevaluated expressions**: An unevaluated `Mul` inside another `Mul` may require recursive per-component analysis, not just one level of iteration.
- **Symbolic factors with assumptions**: A factor like `Symbol('n', integer=True)` should be classified correctly by local analysis, but a bare `Symbol('x')` with no assumptions must yield "unknown" for integrality—not a false positive or negative.
- **Numeric edge cases**: Factors like `S.Half`, `Rational(1, 3)`, or `pi` must be handled correctly in parity/integrality classification; mixing numeric and symbolic factors is where bugs most commonly hide.
- **Expressions that simplify to trivial forms**: E.g., `x / x` constructed unevaluated is structurally a product with `x` and `1/x`, but evaluated it is `1`. The predicate should handle both forms consistently.
- **Power expressions as factors**: A factor like `x**2` where `x` is an integer should be recognized as integer locally, even without global expansion.
- **Empty or single-element compositions**: A product of one factor, or a sum of one term, should degenerate gracefully to the single component's classification.

## PR Examples

- **sympy__sympy-20322**: Predicate for integer-checking on `Mul` expressions used global `as_numer_denom()` decomposition, which produced different numerator/denominator pairs for evaluated vs. unevaluated products of the same mathematical value, leading to inconsistent `is_integer` results. Fixed by switching to per-factor parity and integrality analysis.