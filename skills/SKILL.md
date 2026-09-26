---
name: coding-master
description: use this skill when you are solving coding task.
---

## Core Principles

### 1. Challenge Implicit Assumptions
- **When**: You are writing or reviewing code that passes data across any boundary — between functions, modules, systems, or layers — or that handles input ranges, format expectations, or contracts.
- **Do**: Explicitly identify and verify every assumption about the data's shape, range, nullability, ordering, and ownership rather than relying on conventions; add guards or assertions at trust boundaries.
- **Why**: The majority of bugs across all domains stem from an assumption that was never stated or checked — making implicit assumptions explicit prevents boundary errors, contract violations, and silent data corruption alike.

### 2. Enforce Symmetry in Paired Operations
- **When**: You are implementing any operation that has a logical counterpart — setup/teardown, encode/decode, add/remove, serialize/deserialize, acquire/release, open/close.
- **Do**: Verify that both sides of the pair apply exactly the same transformations in reverse and handle the same set of cases; when you change one side, always update the other.
- **Why**: Asymmetric paired operations cause resource leaks, data corruption, and state divergence that are difficult to diagnose because each side appears correct in isolation.

### 3. Propagate Changes Completely
- **When**: You are modifying a value, format, configuration, or contract that is referenced or depended upon by multiple components.
- **Do**: Trace every consumer of the changed element and update all of them — including error paths, default branches, caches, serialized forms, and documentation — before considering the change complete.
- **Why**: Partial propagation creates silent inconsistencies where some code paths use the old behavior and others use the new, producing bugs that only manifest in specific conditions.

### 4. Guard Every Boundary Condition
- **When**: You are writing logic that processes ranges, collections, optional values, external input, or any data that can be empty, missing, zero-length, at a limit, or in an unexpected format.
- **Do**: Explicitly handle the empty case, the single-element case, the maximum/minimum case, and the malformed case — never assume inputs will be "normal" or "well-formed."
- **Why**: Boundary conditions are the most under-tested paths and the most common source of crashes, off-by-one errors, and security vulnerabilities.

### 5. Respect Ordering Dependencies
- **When**: You are writing code where the sequence of operations matters — initialization before use, validation before processing, acquisition before access, or any multi-step workflow.
- **Do**: Make ordering constraints explicit through structure (e.g., pipeline stages, type states, or sequential composition) rather than relying on implicit call-order conventions or comments.
- **Why**: Implicit ordering dependencies are invisible to future maintainers and easily broken by refactoring, concurrency, or feature additions.

### 6. Match Abstractions to Their Full Contract
- **When**: You are using, wrapping, or implementing an interface, protocol, or abstraction layer — including default values, error semantics, and edge-case behaviors.
- **Do**: Verify that your usage or implementation covers the abstraction's complete contract — not just the happy path — including what it returns on failure, what side effects it has, and what capabilities it actually exposes versus what you assume.
- **Why**: Incomplete abstraction usage causes bugs that hide behind seemingly correct code, surfacing only when the abstraction exercises a contract clause the developer never considered.

### 7. Keep Representations of the Same State in Sync
- **When**: The same logical state is represented in more than one place — caches, derived fields, UI and model, configuration and runtime values, or duplicated data structures.
- **Do**: Use a single source of truth and derive other representations from it, or establish an explicit synchronization mechanism that is triggered on every mutation path.
- **Why**: Independent copies of the same state inevitably diverge, producing inconsistencies that are hard to reproduce and diagnose because each copy appears valid on its own.

### 8. Defend Invariants at Every Mutation Point
- **When**: Your system has a correctness property that must always hold — a uniqueness constraint, a valid-range guarantee, a format contract, or a relationship between fields.
- **Do**: Enforce the invariant at every code path that can mutate the relevant state, not just the primary path; treat any mutation that skips validation as a bug.
- **Why**: Invariants erode silently when secondary mutation paths (error handlers, migrations, bulk operations, environment-specific branches) bypass the checks that the primary path enforces.

## Problem Categories

### Boundary Handling (references/boundary-handling.md)
- Bugs at input boundaries, edge cases, off-by-one errors, or interface mismatches between components.

### API Contract (references/api-contract.md)
- Bugs caused by misunderstanding or violating the expected inputs, outputs, or guarantees of an interface.

### Data Modification (references/data-modification.md)
- Data transformed incorrectly, silently not transformed, or mutated when it should be copied (and vice versa).

### State Synchronization (references/state-synchronization.md)
- Bugs where multiple representations of the same logical state diverge due to missing or incomplete sync mechanisms.

### Type Coercion (references/type-coercion.md)
- Bugs caused by implicit or incorrect conversion between types, formats, or representations.

### Control Flow (references/control-flow.md)
- Bugs where execution takes an unintended path due to incorrect conditionals, missing cases, or logic errors.

### Configuration (references/configuration.md)
- Bugs caused by incorrect, missing, or environment-dependent configuration values and their interaction with code.

### Error Propagation (references/error-propagation.md)
- Bugs where errors are swallowed, misclassified, or incompletely handled as they cross component boundaries.

### Resource Lifecycle (references/resource-lifecycle.md)
- Bugs where resources are acquired but not released, released prematurely, or used after invalidation.

### Concurrency (references/concurrency.md)
- Bugs where concurrent or parallel execution leads to incorrect behavior due to timing, ordering, or synchronization issues.

### General (references/general.md)
- Cross-cutting bugs that span multiple categories or represent novel patterns not yet classified.

## Domains

### api-contract (references/api-contract.md)
- Bugs where code violates, assumes incorrect, or incompletely implements contracts of APIs, protocols, data structures, or interfaces
- file: references/api-contract.md

### boundary-handling (references/boundary-handling.md)
- Bugs at input boundaries, edge cases, interface mismatches, or assumptions about data format, range, and structure.
- file: references/boundary-handling.md

### concurrency (references/concurrency.md)
- Bugs where concurrent or parallel execution leads to incorrect behavior due to timing, ordering, or synchronization issues
- file: references/concurrency.md

### configuration (references/configuration.md)
- Bugs where configuration settings are missing, silently ignored, inconsistently propagated, or produce divergent behavior across code paths.
- file: references/configuration.md

### control-flow (references/control-flow.md)
- Bugs where conditional branching, gating, or path selection causes incorrect execution due to structural flaws in decision logic.
- file: references/control-flow.md

### data-modification (references/data-modification.md)
- Bugs where data is transformed incorrectly, partially, or silently not transformed when it should be.
- file: references/data-modification.md

### error-propagation (references/error-propagation.md)
- Bugs where errors, exceptions, or diagnostic information are caught, translated, reported, or recovered from incorrectly.
- file: references/error-propagation.md

### general (references/general.md)
- Bugs from implicit assumptions, incomplete abstractions, and structural oversights across data transformation, serialization, and dispatch logic
- file: references/general.md

### resource-lifecycle (references/resource-lifecycle.md)
- Bugs where resources are acquired, cached, created, or released incorrectly relative to their expected lifetime or usage scope.
- file: references/resource-lifecycle.md

### state-synchronization (references/state-synchronization.md)
- Bugs where multiple representations, derivations, or copies of the same logical state diverge from each other.
- file: references/state-synchronization.md

### type-coercion (references/type-coercion.md)
- Bugs where implicit or explicit type conversions lose data, misroute control flow, or violate interface contracts.
- file: references/type-coercion.md
