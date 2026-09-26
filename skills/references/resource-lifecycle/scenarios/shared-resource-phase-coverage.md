## Problem Description

A processing pipeline iterates over a collection of items across multiple distinct phases or loops, where each phase needs access to the same shared resource (e.g., a metadata analyzer, a docstring lookup table, a resolved configuration). The shared resource is initialized lazily — only at the point where one particular phase first needs it — leaving earlier phases without access. Those earlier phases silently produce incomplete results (missing metadata, missing docstrings, missing annotations), and downstream filters subsequently discard those incomplete items as "undocumented." The symptom manifests as a subset of items appearing missing or undocumented despite the raw data existing in the source, and it is only observable when items from the starved phase are accessed indirectly (e.g., via inheritance, delegation, or aggregation).

## Root Cause Analysis

The underlying principle is an **ordering dependency on shared resource initialization** that creates an asymmetry between structurally equivalent processing phases. When a resource is initialized inside or just before one consumer loop, all other consumer loops that execute before that point operate in a degraded mode — but silently, without errors. The developer falls into a **false categorization trap**, mentally treating items discovered by different phases as fundamentally different kinds of things, when in reality they all flow through the same downstream filter (e.g., "is this item documented?") and therefore all require equivalent metadata enrichment at discovery time.

This is a form of **symmetry-breaking**: two code paths that should produce items of equal quality instead produce first-class and second-class results, purely because of where the shared resource happens to be constructed. The second-class items are then silently lost by downstream logic that was designed to filter genuinely undocumented items, making the bug appear as a data-source problem rather than a pipeline-ordering problem.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Partial results / silent data loss**: A subset of items that clearly exist in the source appear "undocumented" or are missing from the final output.
  - **Indirect-access-only manifestation**: The missing items are only noticed when accessed through inheritance, re-export, aggregation, or other delegation mechanisms — direct access may work fine.
  - **Phase-dependent enrichment asymmetry**: Debugging reveals that items discovered by one loop/phase carry full metadata while structurally equivalent items from another loop/phase lack it.
  - **No errors or warnings**: The pipeline completes successfully; the data loss is entirely silent.

### 解决步骤
1. **Map all consumers of the shared resource.** Trace every code path within the iteration pipeline that queries or depends on the resource. Do not assume only the "obvious" consumer needs it — check whether earlier loops, branches, or helper functions also produce items that will be evaluated by the same downstream criteria.
2. **Hoist resource initialization to the earliest common ancestor scope.** Move the creation or analysis of the shared resource to a point before ALL consuming loops, not just the one where it was originally placed. If the initialization was inside a try/except block, convert the error handling to set the resource to a sentinel value (e.g., `None`) and guard each consumer with a conditional check.
3. **Add resource lookups to the previously-starved phase.** In the phase that was missing the resource, add the same lookup logic that the already-working phase uses (e.g., querying a docstring dictionary by qualified name). Ensure the lookup is guarded by a check that the resource was successfully initialized.
4. **Verify graceful degradation.** Confirm that when the resource is unavailable (e.g., for built-in types, binary modules, or analysis errors), ALL phases degrade gracefully — producing items without enriched metadata rather than crashing or silently dropping them.
5. **Test with indirect access patterns.** Write tests that exercise items from the previously-starved phase accessed through the indirect mechanism (inheritance, re-export, etc.) to confirm they now carry full metadata and survive downstream filters.

### Why This Works

Moving initialization earlier and applying lookups symmetrically across all phases ensures that the resource's availability is **invariant with respect to which phase processes an item**. This eliminates the ordering dependency that caused the asymmetry. Items are no longer first-class or second-class based on discovery order — they all receive equivalent enrichment, and downstream filters operate on a uniform population. The graceful degradation guards ensure that the fix does not introduce new failure modes for edge cases where the resource genuinely cannot be constructed.

## Boundary Cases
- **Resource initialization can fail legitimately** (e.g., binary/compiled modules, built-in types without source): the hoisted initialization must handle failure by setting a sentinel, not by crashing. Both phases must check for the sentinel before attempting lookups.
- **Items that are genuinely undocumented**: the fix must not cause previously-correct filtering of truly undocumented items to break. The lookup should enrich only when metadata actually exists in the resource.
- **Circular or recursive indirect access**: when inheritance chains or delegation patterns cause the same item to be visited by multiple phases, ensure the resource lookup is idempotent and does not duplicate metadata.
- **Performance impact of early initialization**: if the shared resource is expensive to construct, verify that hoisting it does not cause unnecessary work in code paths that never reach any consumer (consider lazy-but-early patterns where the resource is initialized once on first access by any phase).

## PR Examples
- sphinx-doc__sphinx-8801