## Problem Description

When a public API introduces backward-compatibility mappings for renamed or deprecated identifiers, the translation logic is often applied only at the most visible entry point (e.g., a high-level convenience function), while the underlying data structure — which is itself part of the public API — remains unaware of the mapping. Users who access the data structure directly (via dictionary lookup, membership checks, iteration, etc.) encounter unexpected `KeyError`, `AttributeError`, or similar failures for identifiers that should still be valid under the deprecation policy. This is a **partial-propagation** bug: the deprecation contract is honored on one code path but silently broken on all others.

## Root Cause Analysis

The fundamental cause is **conflating the primary usage pattern with the only usage pattern**. When developers rename or deprecate an identifier, they naturally add a translation shim at the entry point they designed as the "intended" way to use the API. However, if the underlying data structure (a dictionary, registry, lookup table, etc.) is publicly exposed — whether by documentation, convention, or simply by not being prefixed with an underscore — it constitutes an independent access path that is equally part of the API contract.

Because the translation layer lives above the data structure rather than within it, any consumer that bypasses the convenience function and accesses the container directly will never hit the mapping logic. The result is an **incomplete abstraction**: the deprecation exists conceptually but is only enforced at a single point in the call graph, leaving all other paths broken.

A secondary contributing factor is **lifecycle fragility**: even when a custom container with override behavior is introduced, periodic rebuild operations (reload, refresh, re-import) may reassign the module-level variable to a fresh, plain container, silently discarding the override behavior and reverting to the broken state.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - `KeyError` or `AttributeError` when accessing a deprecated-but-supposedly-still-valid identifier through direct container lookup, while the same identifier works fine through a convenience function.
  - Regression reports that surface only for users who interact with the raw data structure (e.g., `module.registry["old_name"]`) rather than the wrapper (e.g., `module.get_item("old_name")`).
  - Inconsistent behavior where membership checks (`"old_name" in module.registry`) return `False` even though the convenience function resolves `"old_name"` successfully.

### 解决步骤

1. **Audit all public access paths.** Enumerate every way a consumer can reach the resource being renamed or deprecated: convenience functions, direct `__getitem__` on exposed containers, `__contains__` / `in` checks, `.get()` calls, iteration, and any re-exports in `__init__.py` or `__all__`.

2. **Push the translation layer down to the data structure level.** Subclass the container (e.g., `dict`) and override the relevant lookup methods — at minimum `__getitem__` and `__contains__`, and often `get` — to intercept deprecated keys, emit a deprecation warning with a clear migration message, and transparently redirect to the new key.

3. **Extract the deprecation mapping and warning message into shared, module-level constants.** Both the convenience function and the custom container should reference the same mapping dictionary and message template, eliminating duplication and guaranteeing that all paths produce identical behavior and messaging.

4. **Protect the custom container from lifecycle reassignment.** If the data structure is periodically rebuilt (e.g., a plugin reload, font cache refresh, or registry rescan), use **in-place mutation** (`container.clear()` followed by `container.update(new_data)`) rather than reassigning the module-level variable. This preserves the custom subclass instance — and its override behavior — even when other modules have already captured a reference to it at import time.

5. **Add tests covering every access path.** For each deprecated identifier, verify correct resolution **and** deprecation warning emission through: (a) the convenience function, (b) direct `container["old_name"]`, (c) `"old_name" in container`, and (d) `container.get("old_name")`. Also test that after a reload/rebuild cycle, the deprecated paths still function.

### Why This Works

By embedding the translation logic in the data structure itself rather than in a wrapper above it, every access path — whether anticipated by the library author or not — automatically benefits from the deprecation mapping. This converts a **partial-propagation** fix into a **total-propagation** fix. The shared mapping constant ensures a single source of truth, and in-place mutation preserves object identity across lifecycle events, preventing silent regression. Emitting warnings at the container level (rather than silently aliasing) maintains the deprecation contract's dual purpose: backward compatibility *and* migration pressure.

## Boundary Cases

- **Container `.get()` with a default value:** If `__getitem__` is overridden but `get` is not, `container.get("old_name", default)` will silently return the default instead of resolving the deprecated key — a subtle, hard-to-detect failure mode.
- **Iteration and serialization:** If the container is iterated (`for key in container`) or serialized (`json.dumps(container)`), deprecated keys will not appear unless explicitly added as aliases. Decide whether deprecated keys should be visible during iteration (usually no, to avoid double-counting) and document the decision.
- **Reload / refresh cycles:** If the rebuild logic reassigns the module-level variable (`module.registry = new_dict()`) instead of mutating in place, any external reference captured before the rebuild will point to a stale object, and the new object will lack override behavior. Both failure modes are silent.
- **Nested or chained deprecations:** If `old_name_A → old_name_B → new_name` (a deprecation chain), the override logic must handle transitive resolution or explicitly forbid chaining, to avoid infinite recursion or partial resolution.
- **Thread safety during rebuild:** If in-place `clear()` + `update()` is not atomic, concurrent readers may observe an empty container between the two calls. Consider holding a lock or swapping contents via a temporary copy.

## PR Examples

- **matplotlib__matplotlib-24265**: Renamed style identifiers were translated in the convenience function (`style.use()`) but not in the publicly exposed `style.library` dictionary. Direct lookup via `style.library["old_name"]` raised `KeyError`. Fix: subclassed `dict` to override `__getitem__` and `__contains__` with deprecation-aware redirection, used in-place mutation during library reload to preserve the subclass instance, and extracted the mapping into a shared module-level constant.