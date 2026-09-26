## Problem Description

When a function dispatches to a specialized code path based on the **structural shape** of a value (e.g., "numerator is 1 and denominator is atomic") rather than its **semantic type** (e.g., "this is a Rational number"), values that happen to share the same algebraic form — but belong to fundamentally different types — are misrouted into logic that cannot handle them. The specialized path then attempts to decompose the value using type-specific assumptions that don't hold, producing wrong output or runtime errors.

A canonical example: a rendering function detects that an expression looks like `1/x` where `x` is atomic, and routes it to a "rational root" display path. A value like `1/e` (reciprocal of a transcendental constant) passes this structural guard but is not a rational fraction. The downstream renderer tries to extract a "root degree" integer from the exponent, fails or produces garbage, and emits incorrect output.

The deeper issue is **passing a raw composite value** to a callee that only needs an already-extracted sub-component. This forces the callee to reverse-engineer the component from the composite, creating a fragile coupling where every new type admitted by the upstream guard must be anticipated by the downstream decomposition logic.

## Root Cause Analysis

The root cause is a **conflation of algebraic form with semantic identity** — an incomplete abstraction where the developer's mental model of the input domain is narrower than the actual domain admitted by the guard condition.

1. **Structural predicates are weaker than type predicates.** A test like "numerator == 1 and denominator is atomic" is satisfied by infinitely many expression types, not just rational fractions. When the specialized path assumes it will only ever see rational numbers, any non-rational inhabitant of the guard triggers incorrect behavior.

2. **Composite-value passing creates hidden contracts.** When a caller passes the full composite (e.g., a fractional exponent) instead of the extracted sub-component (e.g., the root degree), the callee must know how to decompose every possible type the caller might forward. This is inherently fragile because the caller's guard may silently admit new types as the expression algebra evolves.

3. **Missing fallback paths.** Even with correct type checks, there is often no graceful degradation — if the value doesn't fit the specialized path, the code should fall through to a general-purpose renderer, but this fallback is absent.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output on edge cases**: Expressions involving transcendental constants, symbolic reciprocals, or non-rational fractional exponents render incorrectly (garbled strings, missing components, or entirely wrong notation).
  - **Regression on seemingly unrelated inputs**: Adding new constant types or expression forms causes failures in rendering/formatting code that previously worked for rational cases.
  - **Type errors or attribute errors** in decomposition logic that expects a specific type (e.g., calling `.p` and `.q` on a non-Rational).

### 解决步骤

1. **Audit the guard condition and conjoin type predicates.** Locate the structural pattern match that selects the specialized path. Add an explicit type check (e.g., `isinstance(exponent, Rational)`) so that only values with the correct semantic type enter the specialized branch. Values that match structurally but not semantically should fall through to the general path.

2. **Refactor to pass the derived value, not the raw input.** Instead of forwarding the full composite expression to the specialized renderer, extract the sub-component the callee actually needs (e.g., compute the root degree as an integer) at the call site and pass it directly. This makes the interface contract explicit and eliminates the callee's need to reverse-engineer the component.

3. **Use the general-purpose renderer as a fallback.** For sub-components that are too complex for inline display or don't match expected types, call the general rendering function recursively. If the result is unsuitable for the specialized template (e.g., too long for an inline radical notation), fall back to standard power notation.

4. **Add targeted tests for non-obvious guard inhabitants.** Enumerate values that satisfy the structural predicate but are semantically different: reciprocals of transcendental constants (`1/e`, `1/pi`), symbolic expressions that simplify to fractions, and compound expressions with unit numerators. Verify each produces correct output.

### Why This Works

By conjoining structural and semantic predicates, the guard admits only values the specialized path was designed to handle — closing the gap between the developer's mental model and the actual input domain. Passing extracted sub-components rather than composites eliminates the fragile decomposition coupling, making the code resilient to new expression types. The general-purpose fallback ensures that any value not covered by the specialized path still produces correct (if less pretty) output, turning a crash or wrong-output scenario into a graceful degradation.

## Boundary Cases

- **Reciprocals of transcendental constants** (`1/e`, `1/pi`): structurally identical to `1/n` rational fractions but semantically non-rational; must not enter rational-root rendering paths.
- **Symbolic expressions that simplify to fractions** (e.g., `1/Symbol('n')` where `n` is later substituted): the guard may match at construction time but the value is not a concrete rational.
- **Fractional exponents with irrational components** (e.g., `x**(1/sqrt(2))`): the exponent has a unit numerator and atomic denominator but is not a rational root degree.
- **Negative reciprocals** (`-1/e`, `-1/3`): sign handling may differ between the specialized and general paths; ensure both produce correct results.
- **Exponents that are `Rational` but with large or unusual denominators** (e.g., `x**(1/1000)`): technically valid for the specialized path but may produce impractical display; the fallback should handle gracefully.

## PR Examples

- sympy__sympy-20639