## Problem Description

This pattern occurs when computing powers of negative numbers with rational (non-integer) exponents. An optimization path decomposes the exponent into parts — typically using modular arithmetic on the numerator/denominator of a rational exponent (e.g., `p mod q` for exponent `p/q`) — to simplify the sign factor `(-1)^exponent`. This decomposition conflates the periodicity of roots of unity with the branch structure of complex exponentiation, causing the computation to silently select the wrong branch of the multi-valued complex root. The result is that concrete numeric inputs (e.g., `(-2)**(Rational(7,4))`) produce complex-conjugate or otherwise inconsistent results compared to equivalent symbolic expressions (e.g., `(-a)**Rational(7,4)` with `a` substituted as `2`).

## Root Cause Analysis

Complex exponentiation `(-1)^(p/q)` equals `exp(i·π·p/q)`, which depends on the **full value** of `p/q`, not on `p mod q`. Reducing `p mod q` before computing the sign factor effectively changes the angle in the complex plane, jumping to a different sheet of the Riemann surface. This reduction is only mathematically valid when the exponent is an integer, because all branches of the complex logarithm coincide on the real line for integer powers.

The cognitive trap is assuming that because `a^(p/q)` for positive real `a` has a unique positive real value regardless of how `p/q` is represented, the same invariance holds for negative bases. It does not. For negative bases, the principal branch of the complex logarithm introduces a branch cut along the negative real axis, and the full exponent value determines which branch is selected. Modular reduction of the numerator silently selects a different branch, breaking the mathematical equivalence between the original and reduced forms.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Concrete negative base raised to a rational exponent yields the **complex conjugate** of the expected result
  - Substituting a positive symbol into a symbolic negative-base expression (`(-a)**r`) gives a different numeric answer than directly computing `(-2)**r`
  - Inconsistency between `simplify(expr)` and `expr.evalf()` for expressions involving negative bases with rational exponents
  - Results that differ only in the sign of the imaginary part when comparing symbolic vs. concrete evaluation paths

### 解决步骤
1. **Locate the decomposition site**: Find where the rational exponent `p/q` is being decomposed — typically where `p mod q` or `divmod(p, q)` is used to separate the integer and fractional parts of the exponent before computing the sign factor `(-1)^exponent`.
2. **Verify the reduction is branch-unsafe**: Confirm that the reduced form changes the value of `(-1)^(p/q)` by checking a concrete example: `(-1)^(7/4)` via `exp(i·π·7/4)` ≠ `(-1)^(3/4)` via `exp(i·π·3/4)` — these are complex conjugates, not equal.
3. **Replace with unified delegation**: Remove the manual decomposition and instead pass the full, unreduced rational exponent to the symbolic engine's existing handling of `(-1)^exponent`. Let the engine compute `exp(i·π·p/q)` directly.
4. **Validate consistency**: Test that `(-literal)**r` and `(-symbol)**r` (with the symbol substituted to the same value) produce identical results for several rational exponents, including those where `p > q`.
5. **Regression-check integer exponents**: Confirm that integer exponent cases still produce correct real results under the unified path, since the reduction is trivially correct (and unnecessary) for integers.

### Why This Works

Eliminating the modular decomposition in favor of a single symbolic delegation is correct by construction: it avoids re-implementing branch-cut logic in an optimization path. The symbolic engine already handles `(-1)^(p/q)` correctly via `exp(i·π·p/q)`, so delegating to it ensures the full exponent value — and therefore the correct branch — is always used. This guarantees consistency between concrete and symbolic evaluation paths without sacrificing correctness for the integer case (where the unified path naturally reduces to the same result).

## Boundary Cases
- **Integer exponents**: `(-2)**3` — modular reduction is trivially correct here; the unified path must still produce real results
- **Exponents where `p < q`**: `(-2)**(3/4)` — no reduction occurs even in the buggy path, so this case may pass tests while the bug lurks for `p > q`
- **Exponents where `p mod q == 0`**: `(-2)**(4/2)` — reduces to an integer power; must still yield a real result
- **Half-integer exponents**: `(-1)**(3/2)` vs `(-1)**(1/2)` — conjugate pair, a direct test of branch correctness
- **Symbolic negative bases**: `(-a)**(p/q)` where `a` is declared positive — must match concrete evaluation after substitution
- **Large numerators**: `(-1)**(101/4)` — exaggerates the modular reduction error, making it easier to detect

## PR Examples
- sympy__sympy-14024