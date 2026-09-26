## Problem Description

Domain-constraint completeness failures occur when mathematical simplification or optimization rules are implemented with incomplete guard conditions. The rule encodes an identity (e.g., `p^n mod p = 0`, cancellation laws, distributive properties) that is valid only within a specific domain (e.g., integers, positive reals, non-zero values), but the implementation checks only a subset of the required constraints. This causes the rule to fire incorrectly on inputs outside the valid domain, silently producing wrong results rather than raising errors or leaving the expression unsimplified.

This pattern is especially prevalent in symbolic computation systems, computer algebra systems, and any framework that operates over polymorphic or heterogeneous numeric domains where the same algebraic form can represent integer arithmetic, rational arithmetic, real-valued computation, or fully symbolic expressions with unknown properties.

## Root Cause Analysis

The fundamental cause is **integer-arithmetic anchoring** — a cognitive bias where developers mentally model algebraic operations in the integer domain (where divisibility, modular arithmetic, and cancellation behave cleanly) and then fail to recognize that the same algebraic forms have different semantics over rationals, reals, or symbolic unknowns.

When writing a guard condition like "check that the exponent is an integer," the developer's mental model treats this as sufficient because in the integer domain, the base is implicitly also an integer. This creates **partial-constraint blindness**: the guard verifies one operand's properties while silently assuming the same properties hold for other operands. The assumption is invisible precisely because it is always true in the developer's mental test cases.

The danger is amplified in symbolic systems because:
- Variables may have no declared domain, so their properties are unknown at simplification time.
- The same code path handles literal integers, rational numbers, floating-point values, and symbolic expressions.
- Incorrect simplifications produce plausible-looking but mathematically wrong results, making the bug silent rather than loud.

## Solution Strategy

### 识别信号
- 观测到的现象: **Silent data loss / wrong output** — the system returns an incorrect simplified result instead of leaving the expression in its original form or raising an error. For example, `Mod(x**1.5, x)` incorrectly simplifies to `0` when `x**1.5 mod x` is not generally zero for non-integer exponents.
- Simplification rules that produce correct results for integer inputs but wrong results for rational, real, or symbolic inputs.
- Guard conditions that check properties of only one operand in a multi-operand identity.
- Test suites that only exercise integer-valued inputs for rules rooted in integer-domain identities.

### 解决步骤
1. **Enumerate all domain constraints for each identity.** For every mathematical identity used as a simplification rule, write out the complete set of conditions under which it holds. For `p^n mod p = 0`, the constraints are: `p` is a non-zero integer, `n` is a **positive** integer (not just any integer — negative exponents yield fractions). Document these constraints explicitly in comments adjacent to the rule.

2. **Audit guard conditions for completeness.** Compare the implemented guard against the enumerated constraints. Verify that **every** operand involved in the identity is checked, not just a subset. If the identity requires integer inputs, every relevant operand (base, exponent, modulus, divisor, etc.) must be tested for the integer property.

3. **Prefer property-based checks over type-based checks.** Use semantic queries like `expr.is_integer` rather than type checks like `isinstance(expr, Integer)`. Property-based checks correctly handle symbolic expressions that are known to satisfy the property (e.g., a symbol declared with `integer=True`) without being literal instances of the integer type.

4. **Add sign and positivity constraints.** Check that exponents, multipliers, and divisors satisfy not just type constraints but also sign constraints. An exponent must be a **positive** integer for `p^n mod p = 0` to hold; a zero exponent gives `1 mod p = 1`, and a negative exponent gives a fraction.

5. **Write adversarial test cases.** Add tests using non-integer values (1.5, Rational(3, 2)), edge cases (exponent = 0, exponent = -1), symbolic expressions with no declared domain, and mixed-domain inputs to verify the rule does not fire incorrectly. Each test should assert that the expression is returned unsimplified (or correctly simplified) rather than wrongly reduced.

### Why This Works

Mathematical identities are conditional truths — they hold within specific domains but fail outside them. By exhaustively enumerating and checking all domain constraints, we transform an implicitly-scoped rule into an explicitly-scoped one. The rule fires only when all preconditions are provably satisfied, and conservatively leaves the expression unchanged when any constraint cannot be verified. This trades potential missed simplifications (when a constraint is true but unprovable) for correctness — a sound tradeoff in symbolic computation where silent wrong answers are far more costly than missed optimizations.

## Boundary Cases
- **Non-integer exponents:** `Mod(x**1.5, x)` should not simplify to `0`; the identity `p^n mod p = 0` requires `n` to be a positive integer.
- **Zero exponents:** `Mod(x**0, x)` equals `Mod(1, x)`, not `0`. The exponent constraint must be `n ≥ 1`, not just `n ∈ ℤ`.
- **Negative exponents:** `Mod(x**(-1), x)` involves a fraction and the modular identity does not apply.
- **Symbolic operands with unknown domain:** `Mod(a**b, a)` where `a` and `b` are untyped symbols should remain unsimplified since neither integrality nor positivity can be confirmed.
- **Rational base values:** `Mod((3/2)**2, 3/2)` — the identity may not apply if the base is rational rather than integer, depending on how `Mod` is defined over rationals.
- **Floating-point inputs:** `Mod(2.0**3, 2.0)` — even if numerically zero, the simplification rule should not fire based on an integer-domain identity applied to floats, as floating-point semantics differ.

## PR Examples
- **sympy__sympy-13177**: `Mod(x**1.5, x)` was incorrectly simplified to `0` because the guard checked that the exponent was an integer but did not verify that the exponent was specifically a **positive** integer, and did not adequately constrain the base. Non-integer exponents like `1.5` bypassed incomplete checks, triggering the `p^n mod p = 0` identity in a domain where it does not hold.