---
name: state-synchronization
description: Bugs where multiple representations, derivations, or copies of the same logical state diverge from each other.
---

## Overview
These bugs arise whenever a single logical truth is represented, derived, or cached in more than one place, and those representations fall out of sync. The root cause is always a missing, incomplete, or incorrectly structured propagation path between the authoritative source and its dependents.

## Patterns

### Redundant Re-Derivation
- **When**: A downstream component re-derives a value from defaults or a simplified formula instead of reading the already-computed result passed to it by an upstream pipeline that honors custom configuration.
- **Do**: Replace the redundant derivation with a direct read from the upstream-computed value; trace all derived values through every downstream consumer and test with non-default configurations to confirm propagation.
- **Why**: Re-deriving a value creates a second source of truth that diverges whenever the upstream computation path differs from the hardcoded downstream formula — any consumer that falls back to a global default or simplified re-derivation will silently diverge from the explicit input.

### Physical-vs-Logical Identity Divergence
- **When**: A logical rename operation unconditionally triggers physical mutations without checking whether an indirection layer (e.g., explicit physical name overrides) makes the physical state identical before and after.
- **Do**: Resolve effective physical identifiers for both old and new states and short-circuit the entire operation at the orchestration level if they match.
- **Why**: Logical identity changes do not imply physical identity changes when an override layer exists; assuming a 1:1 correspondence causes unnecessary or destructive operations and their cascading side effects.

### Preview/Dry-Run Decision Asymmetry
- **When**: A preview or dry-run path reimplements a multi-factor decision from the execution path but checks only a subset of the conditions.
- **Do**: Enumerate all factors in the execution path's decision and mirror every one in the preview path; test each factor independently set to false.
- **Why**: Duplicated decision logic is a synchronization liability — omitting any condition causes the preview to promise behavior the execution will never perform.

### Optimized-Path Post-Condition Omission
- **When**: An optimized or fast code path replicates the primary effect of an operation but omits a secondary post-condition (e.g., in-memory state cleanup) that the standard path guarantees.
- **Do**: Enumerate the full post-condition contract of the canonical path and verify every alternative path upholds each item; add the missing step inline in the optimized path.
- **Why**: An operation's contract includes all observable effects; optimizations naturally bias toward omitting steps that seem non-essential, silently breaking callers who depend on the full contract.

### Dual-Purpose Flag Conflation
- **When**: A single boolean flag controls both recursion/cycle prevention and observer notification, causing propagated state changes to silently skip callbacks on peer objects.
- **Do**: Decouple the two concerns so that an object always fires its own observer callbacks when its state genuinely changes, regardless of whether it should re-propagate to siblings.
- **Why**: Recursion prevention (who propagates next) and observer notification (who needs to know) are orthogonal; coupling them silences legitimate observers on synchronized peers.

### Wrapper Invariant Non-Enforcement
- **When**: A wrapper class's post-processing logic depends on a mode flag in the inner object that is normally set by an upstream pipeline but not by the wrapper itself.
- **Do**: Set required mode flags explicitly in the wrapper's constructor (on a clone of the inner object) so the wrapper is self-contained; test the wrapper in isolation without the upstream pipeline.
- **Why**: Relying on external code paths to configure an inner object's state creates a hidden coupling that breaks when the wrapper is used outside the expected pipeline.

### Context-Blind Cache Key
- **When**: A cache keys on the explicit input (e.g., expression text) but omits implicit contextual inputs (e.g., namespace, environment) that also determine the result, causing stale cross-context hits.
- **Do**: Include all result-determining inputs in the cache key, or remove the cache entirely if contextual inputs are impractical to key on; test with identical explicit inputs across different contexts.
- **Why**: A cache is only correct when its key uniquely determines the result; omitting context-dependent inputs treats a context-sensitive computation as context-free.

### Derivation Chain Initialization Order
- **When**: Two related configuration properties form a derivation chain (B defaults from A, A defaults from base) but are initialized independently from the shared base, breaking the chain.
- **Do**: Reorder initialization so the downstream property is resolved while the upstream property's explicit-vs-default status is still distinguishable; derive the downstream value from the upstream one when only the upstream is set.
- **Why**: Independent initialization from a shared base treats an asymmetric dependency as symmetric, silently ignoring user customization of intermediate properties.

### Loop-Carried State Reset
- **When**: An iterative loop processes a chain of dependent transformations but copies state from a fixed initial reference each iteration instead of from the previous iteration's result, reverting intermediate mutations.
- **Do**: Reassign the loop's reference variable at the end of each iteration to the fully-mutated result, so the next iteration inherits all accumulated state changes.
- **Why**: When transformations are cumulative — each step's output constrains the next step — using a fixed initial reference discards intermediate mutations and silently reverts state.

### Observer Stale-Reference on Source Update
- **When**: An observer or decorator object is wired to a source at construction time, and the source's properties change after construction, but the observer's update method fails to re-read current source state or trigger necessary auto-resolution before recomputing derived values.
- **Do**: Ensure the observer's update method re-reads current state from the source and triggers any prerequisite resolution (e.g., auto-scaling, limit computation) before recomputing derived outputs; keep the fix at the existing synchronization boundary.
- **Why**: The update method is the designated sync point between source and observer; skipping a re-read or prerequisite resolution step causes downstream computations to operate on stale or uninitialized state.

## Scenarios
- [symmetric-mode-complete-adaptation](./scenarios/symmetric-mode-complete-adaptation.md)
- [parallel-path-filter-symmetry](./scenarios/parallel-path-filter-symmetry.md)
- [cross-subsystem-identifier-canonicalization](./scenarios/cross-subsystem-identifier-canonicalization.md)
- [multi-attribute-consistency-in-partial-state-restoration](./scenarios/multi-attribute-consistency-in-partial-state-restoration.md)
- [inheritance-aware-scope-checking](./scenarios/inheritance-aware-scope-checking.md)
- [empty-set-semantic-ambiguity](./scenarios/empty-set-semantic-ambiguity.md)
- [idempotency-guard-for-reversible-operations](./scenarios/idempotency-guard-for-reversible-operations.md)
- [join-depth-invariant-violation](./scenarios/join-depth-invariant-violation.md)
- [idempotency-assumption-in-state-restore](./scenarios/idempotency-assumption-in-state-restore.md)
- [mutable-environment-assumption](./scenarios/mutable-environment-assumption.md)
- [runtime-mutation-contract](./scenarios/runtime-mutation-contract.md)
- [end-to-end-filter-consistency](./scenarios/end-to-end-filter-consistency.md)
- [snapshot-vs-recomputation](./scenarios/snapshot-vs-recomputation.md)
- [canonical-vs-derived-state-serialization](./scenarios/canonical-vs-derived-state-serialization.md)
- [orm-object-context-affinity-before-field-assignment](./scenarios/orm-object-context-affinity-before-field-assignment.md)
- [lifecycle-coupling-lazy-init](./scenarios/lifecycle-coupling-lazy-init.md)
- [atomic-compound-mutation](./scenarios/atomic-compound-mutation.md)
- [secondary-path-parity](./scenarios/secondary-path-parity.md)
- [consistent-deprecation-across-access-paths](./scenarios/consistent-deprecation-across-access-paths.md)
- [finalization-before-restoration-ordering](./scenarios/finalization-before-restoration-ordering.md)