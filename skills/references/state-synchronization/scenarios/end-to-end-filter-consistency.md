## Problem Description

In multi-phase pipelines that run multiple times within the same process (e.g., analyze → transform → generate), filtering logic applied in early phases may not be replicated in later phases. When shared mutable state (global registries, module-level dictionaries, accumulated collections) persists across sequential invocations with different configurations, artifacts admitted by one invocation's early phases leak into a subsequent invocation's later phases. The result is incorrect output — content is generated for a context or configuration that should have suppressed it — but only when multiple invocations run in sequence, never when each runs in isolation.

## Root Cause Analysis

The fundamental issue is an **implicit assumption of process-level isolation between invocations**. Developers reason about a single pipeline run and conclude that if early phases correctly filter artifacts, later phases will never encounter disqualified data. This assumption holds in single-run scenarios but breaks when the same process reuses accumulated state across runs with different configurations.

The deeper principle is that **each phase in a pipeline must independently enforce its own invariants**. Shared mutable state is a cross-cutting concern that violates phase encapsulation: any prior invocation — not just the current one — can populate it. When a consuming phase (especially the final output/generation phase) trusts the shared state without re-validating eligibility, it becomes vulnerable to **cross-invocation state contamination**. This is a form of state desynchronization where the pipeline's control-flow assumptions (sequential filtering) diverge from the actual data-flow reality (persistent, globally-scoped accumulation).

## Solution Strategy

### 识别信号
- 观测到的现象: Wrong or unexpected output appears **only** when multiple pipeline invocations run sequentially in the same process (e.g., different builder types, different configurations). Each invocation produces correct results when run in isolation.
- Inconsistent state: Later phases operate on artifacts that should have been excluded by the current invocation's configuration, but were admitted by a previous invocation's early phases.
- The bug is non-deterministic with respect to invocation order — it depends on which configurations ran previously and what they left behind in shared state.

### 解决步骤
1. **Map all shared mutable state** consumed by the pipeline. Identify module-level dictionaries, global registries, class-level collections, and any other structures that persist across invocations within the same process.
2. **Trace filtering logic across all phases.** For each phase that applies eligibility constraints (builder type, configuration flags, context), document exactly what conditions it checks and where.
3. **Audit consuming phases (especially the final output/generation phase)** for missing guards. Verify that each phase independently checks eligibility constraints rather than relying on upstream phases to have pre-filtered the shared state.
4. **Add defensive early-return guards** at the beginning of each consuming phase that re-check the same constraints applied by upstream phases. Mirror the existing filtering pattern exactly — use cheap conditionals (e.g., checking builder name, configuration flag) rather than complex refactoring.
5. **Evaluate whether shared state should be cleared between invocations.** If clearing is impractical or introduces risk of breaking other consumers, the defensive guards in consuming phases are the safer, more surgical fix.
6. **Check for adjacent contexts that can never meaningfully use the output** (e.g., single-page builders that cannot use separate module index pages) and add guards for those as well, even if no current bug is observed — this is preventive hardening.

### Why This Works

Defense-in-depth at every phase boundary ensures that no single phase's correctness depends on assumptions about what prior phases (or prior invocations) have done to shared state. Duplicating simple guard checks across phases introduces minimal redundancy — the checks are cheap conditionals — but buys significant robustness against state leakage. This approach respects the reality that shared mutable state is a global resource that any invocation can modify, and treats each phase as a trust boundary that must validate its own inputs.

## Boundary Cases
- **First invocation in a process** will never exhibit the bug, since no prior invocation has contaminated shared state — this makes the issue easy to miss in single-run test suites.
- **Invocation order matters:** the bug may only manifest when a permissive configuration runs before a restrictive one, not vice versa, making it appear intermittent.
- **Clearing shared state between invocations** may fix the immediate symptom but can break other consumers that legitimately depend on accumulated state across phases within a single invocation — prefer guards over clearing unless the state's lifecycle is well-understood.
- **Builders or contexts that are semantically incompatible with certain outputs** (e.g., single-page builders receiving per-module pages) should be guarded even if no cross-invocation contamination is currently possible, as future changes to invocation patterns could expose the gap.
- **Test environments that reuse process state** (e.g., pytest running multiple integration tests in one process) are the most common trigger — the bug may never appear in production if each build runs in its own process.

## PR Examples
- sphinx-doc__sphinx-8721