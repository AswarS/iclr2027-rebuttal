## Problem Description

Discrete mathematical sequence evaluators in symbolic computation systems (e.g., Bell numbers, Catalan numbers, Fibonacci numbers) are implemented with evaluation methods that only handle concrete computable inputs—typically non-negative integers. When special symbolic values like infinity are passed as arguments, these evaluators fall through to a default path that returns an unevaluated symbolic expression (e.g., `bell(oo)`), rather than encoding the mathematically well-defined limiting behavior of the sequence. This creates silent correctness failures where downstream operations like `limit(bell(n), n, oo)` produce nonsensical unevaluated results instead of the expected `oo`.

## Root Cause Analysis

The root cause is an **incomplete abstraction** of the mathematical object being modeled. Developers implement discrete sequence evaluators with a mental model focused exclusively on the "compute a concrete value" use case: given a non-negative integer, look up or calculate the result. Everything else is treated as "not my problem" and deferred by returning an unevaluated expression.

However, in a symbolic computation system, function evaluators are not just calculators—they are the canonical representation of the mathematical function's behavior across its entire domain, including boundary values. Infinity is not an error or an exotic edge case; it is a first-class symbolic value that flows through evaluation pipelines during limit computation, series expansion, and asymptotic analysis. When a sequence is known to diverge, this is an intrinsic mathematical property that must be encoded in the evaluator, not left implicit.

The deeper principle is that **domain boundary behavior is part of a function's specification, not an optional enhancement**. Failing to encode it creates a gap between the mathematical object and its software representation, leading to silently wrong results that are far more dangerous than explicit errors.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `f(oo)` returns an unevaluated symbolic expression like `bell(oo)` instead of `oo`
  - `limit(f(n), n, oo)` returns unevaluated `f(oo)` instead of the mathematically correct limit
  - Passing negative numbers or non-integers to a sequence defined only on non-negative integers returns unevaluated expressions instead of raising errors
  - Downstream symbolic simplifications involving the sequence produce expressions containing `f(oo)` that cannot be further reduced

### 解决步骤
1. **Audit all discrete sequence evaluators** in the codebase to identify which ones only handle concrete non-negative integer inputs in their `eval` method, with a catch-all that returns `None` (unevaluated) for everything else.
2. **Determine the asymptotic behavior** of each sequence: classify as divergent (→ ∞), convergent (→ finite limit), oscillatory, or undefined at infinity. Consult the mathematical definition and known properties.
3. **Add an early boundary check for infinity** at the top of each evaluator's `eval` method, before the concrete computation logic:
   - For divergent sequences: return `S.Infinity` when the argument is `S.Infinity`
   - For convergent sequences: return the known limit value
   - For parameterized variants (e.g., polynomial forms) where infinity is not meaningful: raise `ValueError` with a clear message
4. **Add explicit domain validation** for other out-of-domain inputs: raise `ValueError` for negative numbers and non-integers rather than returning unevaluated expressions.
5. **Check consistency** with how analogous sequence functions in the same codebase already handle these cases, and align behavior patterns across the family of related functions.
6. **Add test coverage** for boundary inputs: `f(oo)`, `f(-1)`, `f(1.5)`, and verify that `limit(f(n), n, oo)` produces the correct result.

### Why This Works

By encoding boundary behavior directly in the evaluator, the function's software representation becomes a faithful model of the complete mathematical object—not just its computable interior. This ensures that symbolic operations like limits, which depend on evaluating functions at boundary points, receive semantically correct inputs and produce correct results. Explicit domain validation converts silent failures (meaningless unevaluated expressions) into loud failures (clear error messages), following the principle that errors should be caught as close to their source as possible.

## Boundary Cases
- **Positive infinity for divergent sequences**: Must return `S.Infinity`, not an unevaluated expression
- **Negative infinity**: May require separate handling depending on whether the sequence has a natural extension to negative arguments (e.g., some sequences are defined for negative integers via analytic continuation)
- **Complex infinity (`zoo`)**: Should be handled explicitly—either return a value or raise an error
- **Negative integer inputs**: Some sequences (e.g., Fibonacci) are defined for negative integers; others are not. Validation must respect the specific sequence's domain.
- **Non-integer inputs**: Sequences like Bell numbers are only defined at non-negative integers; non-integer inputs should raise errors, not return unevaluated expressions
- **Parameterized sequence variants**: Functions like `bell(n, x)` (Bell polynomials) may have different domain constraints than the base sequence `bell(n)`; infinity handling must account for each variant separately
- **Symbolic but finite arguments**: Inputs like `Symbol('n')` should continue to return unevaluated expressions, as they represent unknown-but-finite values

## PR Examples
- sympy__sympy-13437: Bell numbers evaluator returned unevaluated `bell(oo)` instead of `oo` for a divergent sequence, causing `limit(bell(n), n, oo)` to produce incorrect results