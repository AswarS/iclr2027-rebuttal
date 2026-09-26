---
name: concurrency
description: Bugs where concurrent or parallel execution leads to incorrect behavior due to timing, ordering, or synchronization issues
---

## Overview

Concurrency bugs arise when multiple execution contexts (threads, processes, async tasks, actors) interact in ways that violate assumptions about ordering, visibility, or atomicity. These bugs are unified by the fact that correctness depends on controlling or accounting for non-deterministic interleaving of operations.

## Patterns

### Incomplete Protocol Implementation
- **When**: A component must satisfy multiple concurrent interaction protocols (e.g., interfaces, mixins, event contracts) and only partially implements the required surface area.
- **Do**: Verify that all methods/hooks required by every concurrent protocol are implemented; check that composition of multiple protocols doesn't leave gaps where one protocol assumes the other handles a responsibility.
- **Why**: When concurrent participants expect a complete contract, missing operations cause silent failures or undefined behavior under specific interleaving conditions.

### Missing Identity Preservation Under Concurrent Access
- **When**: A transformation or pass-through function is expected to preserve identity semantics but fails to handle all input variants, especially when multiple callers rely on it simultaneously.
- **Do**: Ensure identity/no-op paths cover every possible input type exhaustively; test with the full domain of values that concurrent consumers may supply.
- **Why**: Concurrent consumers assume a shared utility behaves uniformly; incomplete handling causes divergent behavior depending on which caller's input type hits the gap.

### State Visibility Gap
- **When**: One execution context writes state that another context reads, without proper synchronization or memory visibility guarantees.
- **Do**: Identify all shared mutable state and ensure reads and writes are mediated by appropriate synchronization primitives or immutable data structures.
- **Why**: Without visibility guarantees, one context may observe stale or partially-written state, leading to corrupted or inconsistent behavior.

### Atomicity Violation
- **When**: A sequence of operations must execute as an indivisible unit but can be interleaved by other concurrent operations.
- **Do**: Identify compound operations on shared state and protect them with transactions, locks, or atomic primitives that enforce indivisibility.
- **Why**: Interleaving within a logically atomic sequence allows intermediate states to be observed or disrupted by other participants.

### Ordering Assumption Violation
- **When**: Code assumes operations will execute or complete in a specific order, but the runtime provides no such guarantee.
- **Do**: Make ordering requirements explicit through synchronization barriers, sequencing primitives, or dependency declarations rather than relying on implicit timing.
- **Why**: Non-deterministic scheduling means observed ordering in testing may not hold in production, causing intermittent failures.

### Resource Contention Deadlock
- **When**: Multiple execution contexts each hold a resource while waiting to acquire another, forming a circular dependency.
- **Do**: Enforce a consistent acquisition order for shared resources, or use timeout-based or try-lock strategies to break potential cycles.
- **Why**: Circular wait conditions cause all involved contexts to block indefinitely, halting progress.

## Scenarios
- [dual-protocol-mixin-completeness](./scenarios/dual-protocol-mixin-completeness.md)
- [incomplete-identity-function](./scenarios/incomplete-identity-function.md)