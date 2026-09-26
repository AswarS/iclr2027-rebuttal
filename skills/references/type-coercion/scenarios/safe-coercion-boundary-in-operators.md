## Problem Description

When implicit operator methods (such as `__eq__`, `__ne__`, `__lt__`) in a type-coercion system attempt to convert unknown operands into the system's native types, they may inadvertently use a permissive coercion path that falls back to parsing or evaluating the string representation (`repr`) of the foreign object. This creates a "leaky abstraction" where operator-level coercion — which should be safe, side-effect-free, and limited to well-known type mappings — instead executes arbitrary string interpretation logic intended only for explicit, user-facing conversion contexts. The result is that equality checks with foreign objects either crash with unexpected exceptions (attribute errors, syntax errors from the eval path) or produce silently wrong results when a foreign object's string representation coincidentally matches a valid expression in the system's domain.

## Root Cause Analysis

The root cause is a conflation of two fundamentally different coercion contexts:

1. **Explicit/interactive coercion** — a user deliberately passes input (including strings) to a parsing API, expecting the system to interpret it liberally.
2. **Implicit/operator coercion** — the runtime calls `__eq__` or similar dunder methods with arbitrary objects during container lookups, sorting, set operations, or assertions, where the system must behave conservatively.

When both contexts share the same permissive coercion function — one that includes a `repr()`-to-`eval()` fallback — the operator path inherits dangerous behavior. The underlying principle violated is that **display representations are for humans, not for programmatic interpretation in implicit code paths**. The `repr()` of an arbitrary object carries no semantic contract that it is a valid expression in the library's domain, yet the permissive coercion function treats it as such. This is an implicit assumption violation: the operator assumes all objects it encounters either have a known type mapping or a meaningful string representation, when in reality neither may hold.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Equality checks (`==`) with foreign/third-party objects raise unexpected exceptions (e.g., `AttributeError`, `SyntaxError`, `TypeError`) with stack traces passing through string evaluation or parsing logic.
  - Foreign objects with coincidentally matching string representations compare as equal to native objects when they should not (silent wrong output).
  - Crashes appear in implicit contexts: `in` operator on containers, `set()` operations, assertion frameworks, or sorting — anywhere Python dispatches comparison operators automatically.

### 解决步骤
1. **Audit all implicit operator methods** (`__eq__`, `__ne__`, `__lt__`, `__le__`, `__gt__`, `__ge__`, `__hash__`) in the core type hierarchy to identify which coercion function they invoke on their operands.
2. **Distinguish strict vs. permissive coercion functions.** Confirm whether the coercion function used in operators can fall back to string parsing, `eval`, `sympify(str(...))`, or any form of code execution on the operand's string representation.
3. **Replace the permissive coercion call in all operator methods with the strict, type-mapping-only coercion function** — one that converts only well-known, registered types (e.g., `int`, `float`, `Decimal`, `Fraction`) and raises a clear conversion error for anything else.
4. **Handle conversion failures gracefully in the operator.** Catch the conversion error and return `NotImplemented` (for rich comparisons like `__lt__`) or `False` (for `__eq__`), signaling to Python's data model that the objects are not comparable rather than attempting further interpretation.
5. **Preserve the permissive coercion function exclusively for explicit, user-initiated contexts** — interactive input, dedicated parsing APIs (`parse_expr`, `sympify` called directly by the user) — ensuring it is never reachable from implicit operator dispatch.

### Why This Works

Comparison operators are invoked implicitly by Python in countless contexts with objects the library author cannot anticipate. By restricting operator-level coercion to a strict type-mapping boundary, the system guarantees:
- **No side effects or exceptions** from encountering unknown types.
- **No false positives** from coincidental string-representation matches.
- **Correct Python data-model semantics**: returning `NotImplemented` allows Python to try the reflected operation on the other operand, maintaining cooperative comparison behavior.

The strict coercion function embodies the principle that only objects with a well-defined, registered mathematical or domain equivalent should be silently converted. Everything else is explicitly "not comparable," which is the correct semantic answer.

## Boundary Cases
- **Objects whose `__repr__` is a valid expression in the library's domain** (e.g., a logging wrapper whose `repr` is `"2*x + 1"`): strict coercion correctly refuses to interpret this, avoiding false equality.
- **Subclasses or duck-typed objects** that partially implement the library's interface but are not registered for coercion: strict coercion rejects them, and the operator returns `NotImplemented`, allowing the subclass's own reflected operator to handle the comparison.
- **`None`, `NotImplemented`, and sentinel objects** passed into comparisons: strict coercion must not attempt string parsing on these; they should fall through to the "not comparable" return path.
- **NumPy arrays, pandas objects, and other third-party numeric types**: if these are registered in the strict type map, they convert correctly; if not, the operator gracefully declines rather than crashing on their complex `repr`.
- **Recursive or self-referencing `repr` outputs**: the permissive path could hang or crash on these; the strict path never encounters them.

## PR Examples
- sympy__sympy-18057