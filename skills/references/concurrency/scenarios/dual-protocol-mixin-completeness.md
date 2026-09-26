## Problem Description

When a shared mixin or base class provides behavior for both synchronous and asynchronous execution paths, implementing only the synchronous method contract while being composed into a dual-protocol class hierarchy causes the async path to silently fall through to an uninitialized or default state. The framework dispatches to whichever method variant (sync or async) matches the runtime execution model, so a mixin that only overrides the sync variant leaves the async variant unimplemented — typically resolving to `None` or a no-op default inherited from the base class. This results in runtime crashes on the async path (e.g., `TypeError: 'NoneType' object is not callable`) even though the sync path works perfectly.

This is a **symmetry-breaking** problem in **dual-protocol abstractions**: the developer mentally models the mixin through a single execution protocol and fails to recognize that the class hierarchy demands parity across both sync and async contracts.

## Root Cause Analysis

The root cause is **incomplete abstraction at the mixin level** when the class hierarchy enforces a sync/async method pair contract.

Framework base classes often define both a synchronous method and its async counterpart (e.g., `get_response` / `get_response_async`). When neither is overridden, the base class provides coherent defaults for both. However, when a mixin overrides only the sync variant, it breaks the symmetry: the sync path now executes the mixin's custom logic, while the async path falls through to the base class's default — which may return `None`, skip critical processing, or reference an uninitialized attribute.

The cognitive trap is **single-protocol thinking**. Developers trace the call path they are most familiar with (typically sync) and verify correctness there. The async dispatch path is invisible in this mental model, especially when:

- The mixin was originally written before async support was added to the framework.
- The mixin's logic is inherently synchronous (file I/O, legacy code), making async feel irrelevant.
- The base class's async default fails silently or only fails at runtime under async invocation.

## Solution Strategy

### 识别信号
- 观测到的现象: `TypeError` such as `'NoneType' object is not callable` originating from the async response/dispatch pipeline, while the identical operation succeeds on the sync path.
- A mixin or base class overrides a method that has a known sync/async pair in the class hierarchy, but only one variant is overridden.
- The async entry point returns `None` or an unexpected default where a fully-formed response or callable is expected.
- Tests pass for sync views/handlers but crash for async views/handlers using the same middleware or mixin.

### 解决步骤
1. **Audit the class hierarchy for sync/async method pairs.** For every base class the mixin is composed into, enumerate all methods that exist in both sync and async variants (e.g., `get_response` / `get_response_async`, `__call__` / `__acall__`). Document which pairs exist.
2. **For each sync method the mixin overrides, verify the async twin is also overridden.** If the mixin overrides `get_response` but not `get_response_async`, flag this as a symmetry violation.
3. **Implement the async counterpart in the mixin itself.** If the core logic is inherently synchronous (e.g., file system access, CPU-bound computation, legacy code), wrap the synchronous implementation with the framework's async-to-sync bridge utility (e.g., `sync_to_async`) rather than duplicating or rewriting the logic. This correctly offloads blocking work to a thread pool.
4. **Place the override at the mixin level, not in a specific subclass.** This ensures all current and future subclasses that compose the mixin into async hierarchies inherit the correct behavior without requiring each subclass to independently remember the async contract.
5. **Add tests for both execution paths.** For every mixin, write tests that exercise the behavior through both the sync and async entry points to prevent future regressions.

### Why This Works

Sync and async method pairs form a **symmetry contract** in dual-protocol frameworks. The framework dispatches to whichever variant matches the current execution model — if the mixin only intercepts one side, the other side is effectively unguarded. By implementing both variants at the mixin level, the contract is fully satisfied regardless of how the mixin is composed. Wrapping synchronous logic with an async bridge (rather than rewriting) reuses tested code, avoids duplication bugs, and correctly handles blocking operations by offloading them to a thread pool.

## Boundary Cases
- **Mixin logic that is truly async-native:** If the mixin's core logic involves async I/O (e.g., async database queries), the async method should use native `await` rather than wrapping sync code. Only use `sync_to_async` when the underlying operations are inherently blocking.
- **Multiple inheritance diamond problems:** When multiple mixins each override sync/async pairs and are composed together, method resolution order (MRO) must be verified to ensure no variant is shadowed or skipped.
- **Framework version upgrades adding new async variants:** When a framework adds async support to an existing base class method, all existing mixins that override the sync variant become silently broken on the async path. This requires a systematic audit during upgrades.
- **Default base class implementations that appear functional but are incomplete:** Some base classes return a plausible-looking default from the async method (e.g., an empty response instead of `None`), making the symmetry break harder to detect — it manifests as subtle behavioral differences rather than a crash.

## PR Examples
- django__django-12915