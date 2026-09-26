## Problem Description

A specialized numeric transformation routine performs ordered comparisons (e.g., `< 0`, `> 1`, `>= 0`) on values it implicitly assumes are real-valued. However, the routine is reachable through a general-purpose pipeline — such as a simplification engine, recursive expression traversal, or normalization layer — that can feed inputs from a broader domain (complex numbers, symbolic unknowns with no reality assumption, non-numeric types) where ordered comparison is mathematically undefined. The result is a `TypeError` or equivalent exception at the comparison site, triggered by an input the developer never anticipated reaching that code path.

This is a **domain precondition guard** problem: the code's correctness depends on an unstated precondition about the input's mathematical domain, and no explicit check enforces that precondition before the operation that requires it.

## Root Cause Analysis

The underlying cause is **implicit domain assumption violation** compounded by **common-case reasoning** during development.

1. **Ordered comparisons require a total order.** Operations like `< 0` or `> 1` are only meaningful on totally ordered sets (reals, rationals, integers). Complex numbers, symbolic expressions of unknown sign, and certain special values do not support these comparisons. When such a value reaches a comparison operator, the language runtime raises a `TypeError`.

2. **General-purpose pipelines do not pre-filter by domain.** Simplification engines, `rewrite()` methods, and recursive tree walkers are designed to be broadly applicable. They dispatch to specialized transformation rules based on structural pattern matching (e.g., "this is a `sin` of a `Mul`"), not based on the numeric domain of sub-expressions. This means any specialized rule registered in the pipeline is reachable by any structurally matching input, regardless of whether that input satisfies the rule's implicit numeric assumptions.

3. **The cognitive trap.** Developers write transformation rules with typical inputs in mind — integer exponents, rational coefficients, real-valued parameters. They mentally model the "happy path" and forget that the same code path can be reached by `sin(I)`, `cos(zoo)`, or `tan(Symbol('x'))` where `x` has no reality assumption. The assumption that "this value will always be real" is never written down, so it is never checked.

The result is a **contract violation**: the function's internal logic requires a precondition that its interface does not enforce and its callers do not guarantee.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` at an ordered comparison site (`<`, `>`, `<=`, `>=`) inside a transformation or simplification routine.
  - The exception is triggered by complex-valued, symbolic, or otherwise non-real inputs.
  - The crash occurs deep in a call stack that originates from a general-purpose entry point (e.g., `simplify()`, `trigsimp()`, `rewrite()`).
  - The failing code path works correctly for real-valued inputs — the bug is domain-specific, not logic-specific.

### 解决步骤

1. **Locate the comparison site.** Find the exact line where the `TypeError` is raised. Identify what domain property the comparison implicitly requires (e.g., the value must be real, must be finite, must be a concrete number rather than a symbolic unknown).

2. **Trace the call chain upward.** Understand how non-conforming inputs reach this code path. Typically, a general-purpose dispatcher or recursive traversal invokes the transformation without filtering by domain. Confirm that there is no existing guard that should have caught this case.

3. **Add an explicit domain predicate guard.** Insert a check (e.g., `if not value.is_real: return expr` or `if arg.is_real is not True: return expr`) immediately before the ordered comparison, inside the same local function or block. Place it after any existing structural type checks but before any arithmetic comparisons.

4. **Return the expression unchanged on guard failure.** When the domain predicate is not satisfied, the transformation simply does not apply — return the input as-is (identity/no-op). Do not raise an error, do not attempt a fallback transformation, and do not silently produce a wrong result.

5. **Do NOT use try/except or caller-level guards.** The guard must be co-located with the assumption it protects. This makes the precondition explicit, self-documenting, and robust against future callers that might bypass higher-level checks. Catching `TypeError` with try/except masks the root cause and may swallow unrelated errors.

6. **Add test coverage for the broader domain.** Write tests that pass complex-valued, purely symbolic, and other non-real inputs through the general-purpose entry point to confirm the transformation is safely skipped and the original expression is returned.

### Why This Works

The fix converts an **implicit assumption** into an **explicit, testable precondition**. By checking the domain property at the exact site where it is required, the code becomes self-defending: it no longer depends on callers to pre-filter inputs, and it gracefully degrades (returns input unchanged) when the transformation is inapplicable. This follows the principle that **any routine reachable from a general entry point must validate its own domain assumptions**.

Returning the expression unchanged is the correct semantic: the transformation rule is a conditional rewrite — "if this expression has property P, rewrite it as Q." When property P does not hold, the rule simply does not fire, and the expression passes through unmodified. This is consistent with how rule-based simplification systems are designed to work.

## Boundary Cases

- **Symbolic expressions with unknown domain:** `Symbol('x')` with no assumptions — `x.is_real` returns `None` (unknown). The guard should treat `None` as "not confirmed real" and skip the transformation, since proceeding would risk a crash or incorrect result.
- **Complex infinity and special values:** Values like `zoo` (complex infinity), `nan`, or `oo` may partially support comparisons but with surprising semantics. The guard should be strict: only proceed when the required property is definitively `True`.
- **Nested expressions with mixed domains:** An expression like `sin(re(z) + I*im(z))` may have sub-expressions in different domains. The guard must check the specific sub-expression that will be compared, not just the top-level expression.
- **Expressions that become real after evaluation:** `exp(I*pi)` evaluates to `-1` (real), but before evaluation it may appear complex. The guard should work on the current form of the expression; if simplification later makes it real, a subsequent pass can apply the transformation.
- **Multiple comparison sites in the same function:** If a function has several ordered comparisons on different values, each comparison site needs its own guard on the relevant value, not a single guard at the function entry.

## PR Examples

- **sympy__sympy-17139**: A trigonometric simplification rule performed ordered comparisons on exponents assumed to be real-valued. When `simplify()` routed an expression with complex-valued components into this rule, the comparison raised a `TypeError`. The fix added an explicit `is_real` check before the comparison, returning the expression unchanged when the check failed.