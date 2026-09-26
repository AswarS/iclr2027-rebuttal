## Problem Description

When a mathematical operation's internal optimization/simplification logic assumes its arguments will always be compatible with a specific algebraic subsystem (e.g., polynomial machinery), but upstream transformations — such as rewriting, substitution, or simplification under assumptions — produce structurally incompatible subexpressions (e.g., piecewise/conditional expressions), the incompatible arguments propagate into the optimization path and trigger errors from the algebraic subsystem. These errors surface through unrelated user-facing APIs (substitution, simplification, evaluation), making them confusing and seemingly non-deterministic, since the trigger depends on caching state, assumption context, or function composition order.

This is a **graceful-fallback-for-domain-restricted-optimization** pattern: an optional optimization step operates on a restricted domain of expressions, but lacks a guard to verify its inputs belong to that domain before invoking domain-specific machinery.

## Root Cause Analysis

The underlying principle is an **implicit assumption violation** at a capability boundary. The optimization logic (e.g., polynomial GCD extraction inside a modular arithmetic operation) was authored under the assumption that its operands would always be polynomial-compatible — integers, symbols, or polynomial expressions. This assumption is not enforced by any explicit check.

When the broader system evolves or when users compose operations in unanticipated ways, upstream transformations can introduce structurally different expression types (piecewise functions, conditionals, special functions with domain-dependent rewrites) into the operands. The polynomial subsystem correctly rejects these as invalid generators (e.g., "generators do not make sense"), but because the calling optimization has no error boundary, the exception propagates up the call stack and crashes the user-facing operation.

The cognitive trap is twofold:
1. **The original developer assumed a closed world of input types** — a natural but fragile assumption in a symbolic computation system where expression types compose freely.
2. **The optimization is optional** — it improves simplification but is not required for correctness — yet it is invoked unconditionally without a domain check, making it a hard failure point instead of a best-effort enhancement.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A `PolynomialError`, `GeneratorsError`, or similar algebraic subsystem exception propagates through an unrelated user-facing API (e.g., `.subs()`, `.simplify()`, expression evaluation).
  - The traceback passes through an internal simplification or optimization step (e.g., GCD computation, polynomial construction) inside a higher-level operation (e.g., `Mod`, modular arithmetic).
  - The error involves expressions containing `Piecewise`, conditionals, or other non-polynomial subexpressions that were introduced by upstream rewrites or substitutions.
  - The failure may appear non-deterministic, depending on caching, assumption context, or evaluation order.

### 解决步骤
1. **Trace the exception to the optimization boundary**: Identify the specific internal simplification step (e.g., polynomial GCD extraction in `Mod.eval`) where domain-restricted algebraic machinery is invoked on potentially incompatible expressions.
2. **Add a pre-invocation domain check**: Before calling the polynomial operation, inspect the operands for subexpressions that are outside the polynomial domain (e.g., check for `Piecewise` atoms using `.has(Piecewise)` or equivalent). If incompatible subexpressions are found, skip the optimization entirely and fall through to return the unsimplified expression.
3. **Alternatively, wrap with targeted exception handling**: If the set of incompatible expression types is open-ended or hard to enumerate, wrap the polynomial operation call in a `try/except` for the specific polynomial error class. In the handler, skip the optimization (e.g., treat GCD as trivial / no common factor), preserving correctness.
4. **Prefer the explicit pre-check** when the incompatible condition is simple and well-defined, as it is more transparent and avoids masking legitimate errors from the polynomial subsystem.
5. **Add regression tests** covering the trigger path: construct modular (or analogous) expressions whose arguments contain or produce piecewise/conditional subexpressions — via direct construction, substitution of special functions, or simplification under assumptions that trigger domain-dependent rewrites.

### Why This Works

The optimization step (e.g., polynomial GCD simplification) is a **best-effort enhancement** — it produces a more simplified result when applicable, but the unsimplified result is always mathematically correct. By guarding the optimization with a domain check or exception boundary, we convert a hard crash into a graceful degradation: the system returns a correct but potentially less simplified expression. The fix is minimal and targeted because:

- It addresses the root cause at the **responsibility boundary** — the calling operation is responsible for validating that its arguments are suitable for the optimization, not the polynomial subsystem.
- The polynomial machinery is working as designed by rejecting invalid generators; the bug is that it receives invalid input.
- No simplification fidelity is lost for the common case (polynomial-compatible arguments still get the full optimization).

## Boundary Cases
- **Nested piecewise within otherwise polynomial expressions**: An expression like `Mod(x**2 + Piecewise((1, x > 0), (0, True)), 3)` should trigger the guard even though most of the expression is polynomial.
- **Piecewise introduced indirectly by upstream rewrites**: Special functions (e.g., `besselj`, `Abs`) may rewrite to piecewise forms under certain assumptions or substitutions; the guard must catch these even when the original user expression contained no `Piecewise`.
- **Cache-dependent manifestation**: The error may only appear on second evaluation or after certain prior computations populate caches with rewritten forms; tests should cover both fresh and cached states.
- **Other non-polynomial expression types**: Beyond `Piecewise`, expressions containing `DiracDelta`, `Heaviside`, or other distribution-like objects may similarly be incompatible with polynomial machinery; the guard should be extensible or use exception handling as a catch-all.
- **Legitimate polynomial errors**: If using exception handling, ensure only the specific expected error class is caught, to avoid silently masking genuine bugs in the polynomial subsystem or its inputs.

## PR Examples
- sympy__sympy-21379