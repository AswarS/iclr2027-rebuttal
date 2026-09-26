## Problem Description

In symbolic computation systems with associative/commutative operations (like addition and multiplication), a common optimization short-circuits expression reconstruction: if the transformed arguments appear structurally identical to the original arguments, the system returns the original expression unchanged, skipping the canonical constructor. This optimization becomes a correctness bug when transformations (such as substitution, float conversion, or evaluation) cause previously distinct sub-expressions to converge to structurally identical representations. The canonical constructor never sees the converged arguments together, so it cannot combine like terms, cancel opposites, or enforce normal form. The result is expressions like `-0.5*a + 0.5*a` that should simplify to zero but persist as unreduced sums.

## Root Cause Analysis

The fundamental issue is conflating **structural identity** with **semantic invariance**. The short-circuit optimization assumes: "if each individual argument looks the same after transformation, then the overall expression is already in canonical form." This assumption breaks when:

1. **Representation convergence**: Two sub-expressions that were structurally distinct (e.g., `Rational(1,2)*a` vs `0.5*a`) become structurally identical after a transformation like float conversion. The parent expression must be rebuilt for the constructor to detect and merge them.

2. **Canonicalization is holistic**: Canonical constructors for associative/commutative operations (e.g., `Add`, `Mul`) rely on seeing *all* operands in a single flat invocation to detect duplicates, combine coefficients, and cancel terms. Skipping reconstruction denies this holistic view.

3. **Structural identity ≠ semantic equality**: Structural identity is strictly stronger than semantic equality. Using it as a proxy for "nothing meaningful changed" is only valid when the transformation preserves structural identity for unchanged values *and* when no two previously distinct children can converge to the same structure. Numerical evaluation, float conversion, and many substitutions violate both conditions.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Expressions that should simplify to zero (or a simpler form) retain redundant or canceling terms after substitution or evaluation (e.g., `-0.5*x + 0.5*x` instead of `0`).
  - Silent wrong output — no error is raised; the expression simply fails to simplify.
  - The bug manifests specifically after transformations that change representation type (exact → float, symbolic → numeric) while preserving semantic value.
  - Symmetry breaking: `a - a` simplifies correctly, but `subs`-transformed equivalents do not.

### 解决步骤
1. **Locate the short-circuit logic** in the base class for associative/commutative operations (e.g., `Basic._eval_subs`, `AssocOp` reconstruction) where it compares old arguments against transformed arguments to decide whether to return the original expression or reconstruct.
2. **Identify the structural identity check** — typically an `all(old is new for old, new in zip(...))` or equivalent comparison that gates whether the canonical constructor is invoked.
3. **Remove or weaken the short-circuit** so that when any argument has been transformed, the canonical constructor **always runs** on the new argument list. The constructor's built-in canonicalization (flattening, like-term collection, cancellation) must have the opportunity to process all transformed arguments together.
4. **Ensure flat argument passing**: Transformed arguments should be passed as a flat sequence to the canonical constructor rather than wrapped in intermediate sub-expressions. This allows full normalization — combining like terms, detecting cancellations — to operate on all operands at once.
5. **Add regression tests** using pairs of semantically equivalent but syntactically different representations (e.g., exact rationals vs. floats, different symbolic forms) to verify they combine and simplify correctly after transformation.

### Why This Works

The canonical constructor is the single source of truth for normal form in associative/commutative operations. It implements coefficient collection, like-term merging, and identity-element elimination. By ensuring it always runs on transformed arguments, we guarantee that representation convergence caused by transformations is properly exploited. The fix is centralized in the base operations class rather than scattered across individual transformation pipelines, so all transformations that route through standard operation reconstruction benefit from proper canonicalization without each pipeline independently working around the issue.

## Boundary Cases
- **Performance regression**: Always invoking the canonical constructor removes an optimization. For deeply nested expressions where no transformation actually changes anything, this may cause measurable slowdown. Consider a weaker check: skip reconstruction only when arguments are *identical objects* (`is` check) **and** no two arguments share the same identity (no convergence possible).
- **Non-commutative operations**: The flat-passing strategy assumes commutativity/associativity. For non-commutative operations, flattening may change semantics; the fix must respect operation properties.
- **Nested transformations**: A transformation may produce arguments that are themselves non-canonical sub-expressions. The constructor must recursively canonicalize, or the fix only addresses one level of the problem.
- **Hash collisions vs. true equality**: Ensure the convergence detection doesn't rely solely on hash equality, which can produce false positives in rare cases.
- **Infinite recursion**: If the canonical constructor itself triggers substitution or transformation, removing the short-circuit could create cycles. Guard against re-entrant reconstruction.

## PR Examples
- sympy__sympy-13146