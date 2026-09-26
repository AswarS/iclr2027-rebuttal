## Problem Description

When a custom resource-loading pathway (e.g., a custom module importer, plugin loader, or object factory) reimplements parts of a system's standard loading protocol but omits the cache/registry lookup step, duplicate instances of the same logical resource are silently created. These duplicates appear identical but maintain independent mutable state, causing downstream failures such as shared state not propagating, identity checks (`isinstance`, `is`) failing unexpectedly, and initialization side effects seeming to have no effect. The problem is insidious because the duplicated resources look correct in isolation — the bug only surfaces when two independent code paths hold references to different instances of what should be the same singleton object.

## Root Cause Analysis

Standard resource-loading protocols (e.g., Python's import system via `sys.modules`, service locators, DI containers) enforce a **singleton contract**: a canonical identity key maps to exactly one object instance in a global cache. All consumers sharing that key receive the same instance, enabling shared mutable state, reliable identity comparisons, and once-only initialization.

When a custom loader bypasses this cache — even unintentionally — it breaks the singleton contract. The root cause is an **implicit assumption violation**: the custom loader assumes it is the sole entry point for a given resource, or that the resource will only be requested once. In reality, complex systems (test frameworks, plugin architectures, dependency graphs) resolve the same resource through multiple independent code paths. Each invocation of the cache-unaware custom loader produces a fresh instance, and the resulting state desynchronization manifests as baffling bugs far removed from the actual defect site.

The cognitive trap is subtle: the custom loader "works" in simple cases where only one code path triggers it. The contract violation only becomes observable under composition — when multiple subsystems independently request the same resource and expect to receive the same object.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Mutable state set on a resource instance is not visible from another reference to the "same" resource.
  - `isinstance` or `is` identity checks fail between objects that should share the same class or be the same instance.
  - Initialization side effects (e.g., registering hooks, setting module-level variables) appear to have no effect when accessed from a different code path.
  - The problem is intermittent or order-dependent, appearing only when multiple subsystems independently trigger the custom loader for the same logical resource.
  - Debugging reveals two or more distinct objects with the same logical identity key (e.g., same module name, same URI, same registry key) but different `id()` values.

### 解决步骤
1. **Identify the canonical identity key** that the standard loading protocol uses for deduplication (e.g., the fully-qualified module name for `sys.modules`, a URI for resources, a registry key for singletons).
2. **Locate the key-computation point** in the custom loading pathway — the earliest moment where the canonical key is known or can be resolved.
3. **Insert a cache lookup immediately after key computation**, before any creation, instantiation, or initialization logic executes. Check the system's global cache/registry for an existing entry under that key.
4. **Short-circuit on cache hit**: if a cached entry exists, return it directly, bypassing all remaining loading logic.
5. **Store on cache miss**: if no cached entry exists, proceed with the full custom loading logic and ensure the newly created resource is stored in the global cache before returning it to the caller.
6. **Keep the check minimal**: prefer concise idioms (e.g., `try/except KeyError`, `dict.get()`, or `setdefault()`) over verbose conditional blocks to maintain readability and reduce the chance of introducing new bugs.
7. **Assess whether source-validation is needed**: if the key-computation function deterministically and uniquely maps underlying sources to keys, additional validation (e.g., checking file paths match) is unnecessary. If key collisions are possible, add a lightweight consistency check.

### Why This Works

The fix restores the singleton contract by ensuring the custom loader participates in the same global cache that the standard protocol uses. By checking the cache at the earliest possible point — immediately after the canonical key is known — the custom loader becomes a transparent participant in the standard protocol's deduplication mechanism. All code paths, whether they go through the standard loader or the custom one, converge on the same cached instance. This eliminates duplicate objects, restores shared mutable state visibility, and makes identity checks reliable again. The principle is simple: **any code path that can produce an instance of a cacheable resource must first consult the cache, and must populate the cache if it creates a new instance.**

## Boundary Cases
- **Cache entry exists but is stale or partially initialized**: If the standard protocol supports placeholder entries (e.g., partially-initialized module objects in `sys.modules` during circular imports), the custom loader must handle these correctly — either by recognizing and returning them, or by waiting for full initialization.
- **Concurrent loading**: In multi-threaded environments, two threads may simultaneously find the cache empty and both proceed to create the resource. The cache-store step should be atomic or use a locking mechanism to prevent race conditions.
- **Cache invalidation or reload semantics**: Some systems support explicit cache invalidation (e.g., `importlib.reload()`). The custom loader should not interfere with these mechanisms — it should respect cache state as-is at lookup time rather than maintaining a separate shadow cache.
- **Key ambiguity**: If different underlying sources can map to the same canonical key (e.g., symlinks, case-insensitive file systems), the key-computation logic must be normalized to prevent false cache hits or misses.
- **Custom loader invoked as a fallback**: If the custom loader is only invoked when the standard loader fails, the cache may already have been checked by the standard protocol. However, relying on this assumption is fragile — an explicit cache check in the custom loader is still the safest approach, as the invocation contract may change.

## PR Examples
- **pytest-dev__pytest-11148**: A custom module importer in pytest's assertion rewriting machinery omitted a `sys.modules` check before loading, causing duplicate module objects to be created when the same module was imported through different test-collection code paths. The fix was to check `sys.modules` for the target module name immediately before invoking the custom import logic and return the cached module if present.