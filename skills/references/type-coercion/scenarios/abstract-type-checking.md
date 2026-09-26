## Problem Description

Parameter validation logic in libraries uses concrete primitive type checks (e.g., `isinstance(x, int)` or `isinstance(x, float)`) to verify that inputs are of the expected numeric kind. This works correctly when users supply hand-written literal values, but breaks when the same logical values are produced programmatically by numerical libraries, hyperparameter search frameworks, serialization layers, or configuration parsers. These upstream systems commonly emit semantically equivalent numeric scalars (e.g., `numpy.int64`, `numpy.float32`) that do not inherit from Python's built-in `int` or `float` types, causing validation to reject perfectly valid inputs with a `TypeError` or `ValueError`.

This pattern is especially insidious because it is latent — it only manifests when the validated component is embedded in an automated pipeline, making it invisible during manual testing and interactive development.

## Root Cause Analysis

The fundamental error is **conflating a semantic category with a specific concrete type**. "Is an integer" is a semantic property shared by many types (`int`, `numpy.int64`, `numpy.intp`, etc.), but checking `isinstance(x, int)` tests only for one specific implementation of that concept. Python's `numbers` module defines an abstract numeric tower (`numbers.Number` → `numbers.Complex` → `numbers.Real` → `numbers.Rational` → `numbers.Integral`) precisely to express these semantic categories. Well-behaved numeric libraries register their scalar types with the appropriate abstract base classes, so `isinstance(np.int64(3), numbers.Integral)` returns `True` even though `isinstance(np.int64(3), int)` may return `False` on some platforms or numpy versions.

The cognitive trap is that developers test with literal values they type by hand — which are always the built-in type — and never encounter the mismatch. This creates a false sense that the type check is complete. The bug surfaces only when an automated framework (e.g., `GridSearchCV`, `RandomizedSearchCV`, JSON config loaders) generates parameter values using library-specific numeric types.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError` or `ValueError` during parameter validation when values come from automated pipelines, but not when the same logical values are supplied as Python literals.
  - Crash traces pointing to `isinstance(value, int)` or `isinstance(value, float)` checks in validation utilities.
  - The error disappears if the user manually wraps values with `int(...)` or `float(...)` before passing them in.
  - Failures are intermittent across environments because some platforms/library versions may or may not have their scalar types inherit from built-in primitives.

### 解决步骤
1. **Audit the validation scope**: Identify all `isinstance` checks and type comparisons in the affected validation function or module that use concrete primitive types (`int`, `float`, `bool`, `str`). Do not limit the search to the single parameter mentioned in the bug report.
2. **Replace concrete types with abstract base classes**: Substitute `int` with `numbers.Integral`, `float` with `numbers.Real` (or `numbers.Number` where appropriate). Import from the `numbers` standard library module. Avoid enumerating specific third-party types (e.g., `(int, np.integer)`) as this couples the code to specific libraries and misses future types.
3. **Handle edge cases for `bool`**: Since `bool` is a subclass of `int` (and `numbers.Integral`), add an explicit `not isinstance(x, bool)` guard if boolean values should be rejected for a parameter that expects integers.
4. **Propagate the fix systematically**: Apply the same abstract-type-check pattern to every parameter validated in the same scope. Each concrete check has the same latent vulnerability; spot-fixing only the reported parameter guarantees a repeat bug report.
5. **Add regression tests**: Write test cases that pass numeric values from common external libraries (e.g., `numpy.int64`, `numpy.float32`, `numpy.int32`) through the validation path and assert they are accepted without error.

### Why This Works

Abstract numeric base classes define the **semantic contract** — "is an integer", "is a real number" — rather than an implementation detail. Any well-behaved numeric type registers with these ABCs (numpy, sympy, gmpy2, etc.), so checking against them is both more correct and more future-proof. This approach:
- Decouples validation from specific third-party library types.
- Automatically covers current and future numeric type implementations.
- Aligns the code's intent (accept any integer-like value) with its mechanism (check against the abstract integer category).
- Eliminates an entire class of bugs rather than playing whack-a-mole with individual type mismatches.

## Boundary Cases
- **Boolean rejection**: `bool` is a subclass of `numbers.Integral`. If a parameter should accept integers but reject booleans, an explicit `isinstance(x, bool)` exclusion must be added.
- **String-encoded numbers**: Values like `"3"` or `"1.5"` from configuration files are not `numbers.Integral` or `numbers.Real`. If string-to-number coercion is desired, it must be handled separately before the type check.
- **Complex numbers**: `numbers.Real` excludes complex types, but `numbers.Number` includes them. Choose the appropriate level in the abstract tower based on the parameter's mathematical domain.
- **Duck-typed numeric objects**: Some objects implement `__int__` or `__float__` without registering with the `numbers` ABCs. If these must be accepted, an explicit conversion attempt (`int(x)`) with error handling may be needed in addition to the ABC check.
- **Numpy 0-d arrays vs. scalars**: `numpy.array(3)` (a 0-dimensional array) is distinct from `numpy.int64(3)` (a scalar). The former may not register as `numbers.Integral`. Decide whether 0-d arrays should be accepted and handle accordingly.
- **Platform-dependent behavior**: On some platforms, `numpy.int_` may or may not be a subclass of Python's `int`. Using `numbers.Integral` abstracts away this platform variance entirely.

## PR Examples
- **scikit-learn__scikit-learn-14092**: Parameter validation in scikit-learn estimators used `isinstance(x, int)` and `isinstance(x, float)`, causing failures when `GridSearchCV` or `RandomizedSearchCV` supplied numpy scalar types. Fixed by replacing concrete type checks with `numbers.Integral` and `numbers.Real` across the validation utilities.