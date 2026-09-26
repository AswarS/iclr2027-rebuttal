## Problem Description

When a composite/delegating structure (e.g., a union, intersection, or difference of sub-components) receives a state-changing operation — such as "mark as empty," "disable," or "reset" — the operation is applied only to the top-level wrapper but fails to propagate to the constituent sub-components. Because the composite's actual behavior emerges from its parts rather than from the wrapper itself, the state change has no observable effect: the sub-components continue to execute their original logic independently, producing results as if the mutation never occurred.

This pattern manifests wherever a composite object delegates its core behavior (result generation, rendering, execution) to a collection of inner parts, and a mutation API exists that callers expect to affect the composite's output holistically.

## Root Cause Analysis

The fundamental issue is **treating a composite as if it were atomic**. Developers assume that setting a flag or modifying state on the top-level wrapper is sufficient to alter the composite's behavior, but the wrapper is merely an orchestrator — it assembles its output by iterating over and combining the outputs of its sub-components. Each sub-component operates independently and has its own state. When only the wrapper is mutated, the sub-components remain untouched and continue producing their original output.

A secondary, compounding cause is **shallow cloning**. Composite structures often support clone/copy operations (e.g., for branching query construction). If the clone shares sub-component references with the original, then propagating a mutation through the clone's sub-components will corrupt the original's sub-components as well. This turns a correct propagation fix into a shared-mutable-state bug, which is why developers may have avoided propagation in the first place.

Together, these two gaps — missing recursive propagation and insufficient clone depth — create a situation where state changes on composites are silently ignored, leading to wrong output or silent data loss.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Applying a state change (e.g., "set as empty," "disable") to a composite structure has **no observable effect** — the composite still produces results from its unchanged sub-components.
  - **Silent data loss or wrong output**: operations that should yield empty/modified results instead return stale or full results.
  - The structure delegates behavior to a list/collection of inner parts (sub-queries, child nodes, member components).
  - A clone/copy mechanism exists, and mutations may be applied to clones independently of originals.

### 解决步骤

1. **Determine if the structure is composite or atomic**: Inspect whether the object's core behavior (e.g., result generation, SQL rendering, output assembly) is delegated to a collection of sub-components. If the object iterates over inner parts to produce its output, it is composite and requires recursive propagation.

2. **Ensure deep cloning of sub-components**: Before adding propagation logic, verify that the clone/copy operation creates fully independent copies of all sub-components. If sub-components are shared by reference, modify the clone method to deep-copy them. This prevents mutations on a clone from corrupting the original.

3. **Propagate state-changing operations recursively**: In every method that mutates the composite's state (e.g., `set_empty()`, `set_disabled()`, `clear()`), add logic to iterate over all sub-components and apply the same state change to each one. The wrapper's own state should also be updated for consistency, but the critical fix is ensuring the parts reflect the change.

4. **Verify correctness with a round-trip test**: Create a composite, clone it, apply the state change to the clone, and assert:
   - **(a)** The clone reflects the change across all sub-components (e.g., produces empty/modified output).
   - **(b)** The original remains completely unaffected (no shared-state corruption).

### Why This Works

The composite's output is an aggregation of its sub-components' outputs. Mutating only the wrapper is a no-op because the wrapper doesn't directly produce results — it delegates to its parts. By propagating the mutation to every sub-component, the state change reaches the actual sources of behavior. Deep cloning ensures that this propagation is safe: cloned composites can be mutated independently without side effects on the original, preserving the expected copy semantics that callers rely on.

## Boundary Cases

- **Nested composites**: Sub-components may themselves be composites (e.g., a union of unions). Propagation must be fully recursive, not just one level deep.
- **Mixed atomic and composite sub-components**: Some sub-components may not support the state-changing operation. Propagation logic should check for capability or use a common interface.
- **Empty sub-component collections**: A composite with zero sub-components should still update its own wrapper state, as it may later acquire sub-components.
- **Concurrent or repeated mutations**: Applying the same state change multiple times (idempotency) should not cause errors or compounding side effects.
- **Lazy or deferred sub-components**: If sub-components are lazily initialized, the propagation must account for components that don't yet exist at mutation time — either by eagerly initializing them or by recording the state for later application.

## PR Examples

- **django__django-13158**: A combined queryset (union/intersection/difference) failed to propagate `set_empty()` to its sub-queries, causing the composite to still return results when it should have been empty. The fix required both deep-cloning the sub-queries during copy and recursively applying the state change to each sub-query.