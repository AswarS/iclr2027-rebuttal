## Problem Description

When implementing a transparent proxy or lazy-wrapper object that delegates arithmetic and other binary operations to an underlying wrapped object, the proxy fails with `TypeError` when it appears as the **right-hand operand** in binary expressions (e.g., `5 + proxy_obj`). This occurs because the proxy only implements forward magic methods (`__add__`, `__mul__`, etc.) through a uniform delegation/code-generation pattern, but omits the corresponding reflected/reversed operator methods (`__radd__`, `__rmul__`, etc.) that Python's operator dispatch protocol requires for right-hand-side participation.

The pattern is particularly insidious because the proxy appears to work correctly in all cases where it is the left operand, creating a false sense of completeness. The failure only surfaces when a non-proxy value is on the left and the proxy is on the right — a scenario that is common in real-world usage but easy to miss in initial testing.

## Root Cause Analysis

Python's binary operator dispatch protocol is **asymmetric by design**. When evaluating `a + b`:

1. Python first tries `a.__add__(b)`.
2. If that returns `NotImplemented` (or doesn't exist), Python falls back to `b.__radd__(a)`.

A proxy that only implements `__add__` by forwarding to `self._wrapped.__add__(other)` will work when the proxy is `a`, but when the proxy is `b`, Python needs `b.__radd__(a)` — which doesn't exist. The left operand's `__add__` returns `NotImplemented` because it doesn't know how to handle the proxy type, and there is no reflected method to fall back to.

The deeper cognitive trap is **conflating delegation with protocol completeness**. Uniform code-generation patterns (e.g., `__method__ = make_proxy(operator.method)`) create a long, impressive-looking list of forwarded methods that gives developers false confidence. However, reflected operators require a fundamentally different implementation strategy — they are not simple forwarding but require **operand reversal**: `return other <op> self._wrapped` rather than `return self._wrapped <op> other`. Most standard libraries (e.g., Python's `operator` module) do not provide `operator.radd` equivalents, so the same mechanical template cannot be reused.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `TypeError: unsupported operand type(s)` when a proxy/lazy object appears as the **right-hand operand** in a binary expression
  - Forward operations (`proxy + 5`) work correctly, but reversed operations (`5 + proxy`) crash
  - The proxy class has a long list of generated/templated forward operator methods but no corresponding `__r*__` methods
  - Users report inconsistent behavior depending on expression ordering

### 解决步骤
1. **Audit all implemented forward operator methods** on the proxy class and catalog which ones have a corresponding reflected counterpart (`__add__` → `__radd__`, `__sub__` → `__rsub__`, `__mul__` → `__rmul__`, `__mod__` → `__rmod__`, `__truediv__` → `__rtruediv__`, `__floordiv__` → `__rfloordiv__`, `__pow__` → `__rpow__`, `__and__` → `__rand__`, `__or__` → `__ror__`, `__xor__` → `__rxor__`, `__lshift__` → `__rlshift__`, `__rshift__` → `__rrshift__`, `__matmul__` → `__rmatmul__`).

2. **Implement each reflected operator as a custom method** that: (a) triggers lazy initialization / resolution of the wrapped object, and (b) performs the operation with **reversed operand order**: `return other <op> self._wrapped`. Do not simply forward to `self._wrapped.__radd__` — instead, express the operation naturally with the wrapped value in the secondary position.

3. **Reuse the existing proxy initialization mechanism** (e.g., a decorator or setup function) to wrap each reflected method, ensuring that lazy initialization is still triggered transparently before the operation executes.

4. **Enforce a symmetry rule**: whenever a forward operator is added to the proxy, the corresponding reflected operator must be added in the same change. Treat them as an inseparable pair.

5. **Add comprehensive tests** covering:
   - `proxy <op> value` (forward — should already work)
   - `value <op> proxy` (reflected — the newly fixed case)
   - `proxy <op> proxy` (both operands are proxies)
   - Edge cases with `NotImplemented` returns and mixed types

### Why This Works

By implementing reflected operators with proper operand reversal, the proxy correctly participates in Python's two-phase operator dispatch. When `5 + proxy` is evaluated, `int.__add__(5, proxy)` returns `NotImplemented` because `int` doesn't know about the proxy type. Python then calls `proxy.__radd__(5)`, which resolves the wrapped object and computes `5 + wrapped_value` — completing the dispatch chain. The proxy becomes truly transparent in both operand positions, fulfilling the contract that a proxy should be indistinguishable from the object it wraps.

## Boundary Cases

- **Both operands are proxies**: `proxy_a + proxy_b` — the forward method on `proxy_a` will attempt `proxy_a._wrapped + proxy_b`, which may trigger `proxy_b.__radd__` if the wrapped type doesn't understand the proxy. Ensure reflected methods also handle proxy arguments by resolving the other operand if it is also a proxy.
- **Wrapped object itself returns `NotImplemented`**: If `self._wrapped` doesn't support the operation with the given `other` type, the reflected method should propagate `NotImplemented` rather than raising, to allow Python's dispatch to continue or produce the correct `TypeError`.
- **In-place operators (`__iadd__`, etc.)**: These follow a similar but distinct protocol. If the proxy implements in-place operators, verify they also handle cases where the wrapped object doesn't support in-place mutation (falling back to creating a new object).
- **`__pow__` with three arguments**: `__rpow__` has a unique signature consideration (`pow(base, exp, mod)`) — ensure the reflected version handles the optional third argument correctly.
- **Comparison operators (`__eq__`, `__lt__`, etc.)**: While not traditionally called "reflected," they have mirrored pairs (`__lt__` ↔ `__gt__`, `__le__` ↔ `__ge__`). Audit these for the same asymmetry issue.
- **Uninitialized/unresolved proxy state**: Ensure that the lazy initialization mechanism in reflected methods handles errors during resolution gracefully, without leaving the proxy in a corrupted half-initialized state.

## PR Examples

- **django__django-15400**: Django's `SimpleLazyObject` (and related lazy proxy utilities) implemented forward arithmetic operators via a uniform code-generation pattern but omitted all reflected operators (`__radd__`, `__rsub__`, `__rmul__`, etc.), causing `TypeError` when lazy objects appeared as the right-hand operand in binary expressions.