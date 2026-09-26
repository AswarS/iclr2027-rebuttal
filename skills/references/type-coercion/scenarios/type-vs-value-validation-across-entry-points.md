## Problem Description

A public API accepts a numeric parameter that semantically requires an integer (e.g., a count, index, or discrete quantity) but only validates the parameter's value range (e.g., `> 0`), not its type. The same parameter can be supplied through multiple independent entry points (e.g., at construction/fit time and again at query/predict time), with validation present at only one of them—or none at all. When a non-integer type (such as a float) eventually reaches a strict-typed internal layer (C extension, system call, or typed data structure), it produces an opaque, unhelpful error that gives the user no indication of which parameter was wrong or why.

This is a compound defect: **missing type validation** combined with **asymmetric validation across entry points**, resulting in confusing errors that surface far from the API boundary where the mistake was made.

## Root Cause Analysis

Three interacting cognitive traps produce this pattern:

1. **Conflation of numeric validity with type validity.** In dynamically typed languages, `3.0` and `3` are arithmetically equivalent and both pass range checks like `> 0`. Developers assume that passing a range check is sufficient, forgetting that downstream consumers (C extensions, array indexing, protocol buffers, system calls) distinguish between integer and floating-point types. Range validation does not imply type validation.

2. **Single-checkpoint validation assumption.** When a parameter can enter the system through multiple independent code paths (e.g., `__init__`, `fit`, `predict`, `query`), developers validate at the first or most obvious entry point and assume all subsequent uses are safe. They overlook that later calls can supply a fresh, completely unvalidated value that bypasses the original check entirely.

3. **Preference for silent coercion over explicit rejection.** When the mismatch is noticed at all, the instinct is to silently cast (`int(x)`) rather than raise a clear error. This papers over conceptual misunderstandings—e.g., a user confusing a continuous radius parameter with a discrete neighbor-count parameter—and delays the discovery of real bugs.

The underlying principle: **validation must be both type-aware and symmetric across all entry points**, because any gap between "what the API accepts" and "what the internals require" becomes a source of confusing, hard-to-diagnose failures.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Opaque `TypeError` or `ValueError` originating from a low-level layer (C extension, Cython, system call) rather than from the public API boundary.
  - Error messages that reference internal variable names or implementation details instead of the user-facing parameter name.
  - A parameter that passes validation at one entry point (e.g., constructor) but causes failures when supplied at another entry point (e.g., query method) with the same value.
  - Float values like `3.0` accepted silently at the API level but causing downstream breakage.
  - Inconsistent behavior: the same logical parameter validated differently (or not at all) depending on which method receives it.

### 解决步骤

1. **Audit all entry points for the parameter.** Trace every public method where the parameter can be supplied or overridden. Map the complete set of code paths from API boundary to internal consumption. Do not assume the constructor is the only entry point.

2. **Define a strictness policy before writing code.** Decide explicitly: should non-integer types be rejected with a `TypeError`, or silently cast? Prefer strict rejection for discrete/count parameters, because silent casting masks semantic misunderstandings. Document this decision.

3. **Implement explicit type validation at each entry point.** Check `isinstance(value, numbers.Integral)` (or equivalent) before any range or domain checks. Raise a clear, descriptive `TypeError` that names the parameter, states the expected type, and shows the received type and value.

4. **Extract validation into a shared helper.** Create a single reusable validation function (e.g., `_check_integer_param(value, name, lower_bound=None)`) and call it from every entry point. This eliminates drift between validation logic at different call sites and ensures symmetric coverage.

5. **Add comprehensive tests for each entry point.** Cover: correct integer values, float equivalents of integers (e.g., `3.0`), non-numeric types (strings, `None`), boundary values (zero, negative), and numpy integer/float types. Verify that the error message is actionable and references the parameter by name.

### Why This Works

By validating type and value at every API boundary through a shared helper, the system enforces a single, consistent contract regardless of which entry point the user calls. Failures are caught at the point closest to the user's mistake, producing actionable error messages. The shared helper eliminates the symmetry-breaking problem where one path validates and another does not. Strict rejection over silent casting surfaces conceptual errors early, following the principle of least surprise.

## Boundary Cases

- **Numpy integer types** (e.g., `np.int64`, `np.intp`): these are valid integers but are not instances of Python's `int`. Validation must use `numbers.Integral` or explicitly include numpy integer types to avoid false rejections.
- **Boolean values**: `bool` is a subclass of `int` in Python, so `True`/`False` pass `isinstance(x, int)` checks. Decide whether booleans should be accepted for count parameters (usually they should not) and add an explicit check if needed.
- **Float values that are mathematically integers** (e.g., `3.0`): these pass range checks and even `float.is_integer()`, but accepting them silently undermines the type contract. The policy decision here should be explicit and consistent.
- **Parameters with default values of `None`**: when `None` means "use the value from construction time," the query-time validation must allow `None` to pass through while still validating any non-`None` override.
- **Subclassed or wrapped numeric types**: custom numeric types that implement `__int__` but are not `numbers.Integral` may need special handling depending on the API's contract.
- **Negative integers for inherently non-negative parameters**: type validation alone is insufficient; the shared helper must also enforce domain constraints (e.g., `>= 1` for counts).

## PR Examples

- **scikit-learn__scikit-learn-11040**: A neighbor-count parameter (`n_neighbors`) was validated for range but not type at the constructor, and not validated at all at the query method. Passing a float like `3.0` at query time propagated to a C extension that raised an opaque error. The fix required adding symmetric type-and-value validation at both entry points.