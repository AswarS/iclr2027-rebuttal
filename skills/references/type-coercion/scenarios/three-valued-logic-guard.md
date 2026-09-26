## Problem Description

When validation logic tests the truthiness of a symbolic or lazily-evaluated expression to enforce a constraint (e.g., "is this value zero?", "is this quantity positive?"), the guard silently conflates three distinct states — **provably true**, **provably false**, and **indeterminate** — into a binary true/false decision. This causes the system to incorrectly reject valid inputs whenever the expression remains in unevaluated or partially-simplified form, because an unevaluated symbolic object is truthy as a Python object even when it mathematically represents zero (or another passing value). The problem is latent under eager evaluation (where expressions fully resolve) but surfaces as crashes or false rejections when evaluation is deferred, suppressed, or when inputs are fully symbolic.

## Root Cause Analysis

Symbolic computation systems operate in **three-valued logic**: property queries like `.is_zero`, `.is_positive`, `.is_integer` return `True`, `False`, or `None` (indeterminate). However, Python's truthiness model is strictly two-valued — `bool(obj)` must return `True` or `False`. When a guard is written as `if computed_value:` or `if not computed_value:`, it evaluates the Python truthiness of the expression object itself, not its mathematical truth value. An unevaluated symbolic expression like `im(x) + im(y)` is a non-None, non-zero Python object and therefore truthy, even though it mathematically equals zero for real-valued `x` and `y`.

The underlying cognitive trap is the **implicit assumption that computation always fully resolves**. Under eager evaluation this assumption holds and the guard works by accident. But the system's contract permits deferred evaluation, lazy simplification, and symbolic unknowns — contexts where intermediate results remain as unevaluated expression trees. The guard must respect the three-valued semantics of the symbolic layer rather than collapsing them through Python's two-valued truthiness.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Crash or exception** (e.g., `TypeError`, `ValueError`) when calling a function with `evaluate=False` or in a deferred-evaluation context, while the same call succeeds under normal evaluation.
  - **Regression on edge cases**: valid mathematical inputs are rejected by a validation guard that previously accepted them, triggered by changes in simplification behavior or evaluation mode.
  - **Environment-dependent behavior**: identical mathematical inputs produce different outcomes depending on whether evaluation is eager or deferred.

### 解决步骤

1. **Locate all validation guards that test truthiness of symbolic expressions.** Search for patterns like `if expr:`, `if not expr:`, `if expr != 0:`, or `if expr == 0:` where `expr` is a computed symbolic result. Pay special attention to guards that enforce mathematical constraints (e.g., "imaginary part must be zero", "denominator must be nonzero").

2. **Determine the three-valued semantics of the check.** For each guard, identify the relevant symbolic property query (`.is_zero`, `.is_nonzero`, `.is_positive`, `.is_real`, etc.) and confirm that it returns `True`, `False`, or `None`. Understand what the `None` case means: "the system cannot determine the answer with current information."

3. **Replace the two-valued truthiness test with an explicit three-valued identity check.** Choose the conservative direction:
   - To **reject only when a violation is provably true**, use `if property is False:` (or `is True` for the converse). This treats `None` (indeterminate) as permissive.
   - Example: replace `if im_part:` (intended to reject nonzero imaginary parts) with `if im_part.is_zero is False:` — this only rejects when the imaginary part is **provably** nonzero, and permits both zero and indeterminate cases.

4. **Verify under all evaluation contexts.** Test with: (a) eager evaluation and concrete numeric inputs, (b) `evaluate=False` or deferred evaluation, (c) fully symbolic/unknown inputs where properties return `None`. Confirm that valid inputs pass in all three contexts and genuinely invalid inputs are still caught.

### Why This Works

By using explicit identity checks (`is True`, `is False`) against the three-valued property API, the guard correctly distinguishes between "provably violates the constraint" and "might or might not violate the constraint." The conservative approach — only raising an error when violation is **proven** — prevents false rejections while preserving the ability to catch genuinely invalid inputs. This aligns the validation logic with the symbolic system's actual contract rather than relying on an accidental property of Python object truthiness.

## Boundary Cases

- **Unevaluated composite expressions**: An expression like `im(a) + im(b)` that mathematically simplifies to zero but remains as an unevaluated sum. The `.is_zero` property may return `None`, which the guard must treat permissively.
- **Mixed concrete/symbolic inputs**: Some sub-expressions resolve to concrete values while others remain symbolic. The overall expression's properties may be indeterminate even though parts are known.
- **Evaluation mode switches mid-computation**: A function called with `evaluate=False` that internally calls sub-functions which may or may not respect the flag, producing partially-evaluated results.
- **Expressions that are trivially zero but not simplified**: e.g., `x - x` in a context where automatic cancellation is suppressed. The object is truthy but mathematically zero.
- **None-returning property queries chained with boolean operators**: `if expr.is_zero and other_condition:` — when `.is_zero` returns `None`, Python's short-circuit evaluation treats `None` as falsy, silently skipping the branch. This is a subtle variant of the same bug.

## PR Examples

- **sympy__sympy-22714**: A validation guard in SymPy tested the truthiness of a computed imaginary-part expression to enforce a "must be real" constraint. Under `evaluate=False`, the imaginary part remained as an unevaluated symbolic sum (truthy Python object) rather than simplifying to zero, causing a false rejection. The fix replaced the truthiness test with an explicit `.is_zero is False` check, correctly handling the indeterminate case.