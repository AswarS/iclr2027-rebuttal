---
name: resource-lifecycle
description: Bugs where resources are acquired, cached, created, or released incorrectly relative to their expected lifetime or usage scope.
---

## Overview

Resource-lifecycle bugs occur when the creation, retention, sharing, or teardown of a resource (handle, connection, table, cached reference, lock) is misaligned with the actual need for that resource or with the constraints governing its existence. The unifying theme is a mismatch between when/where a resource exists and when/where it should exist.

## Patterns

### Unconditional Setup Before Policy-Gated Operations
- **When**: An infrastructure setup step (e.g., creating a tracking table, provisioning a queue) runs unconditionally even when access-control or routing rules will prevent the main operation from executing on that target.
- **Do**: Guard the setup step on whether actual work will proceed; place the guard at the orchestration layer so the setup's side effects only occur when the operation it supports will actually execute.
- **Why**: The first execution of a "safe to repeat" setup step on a restricted target violates access policy — idempotency does not imply universal permissibility.

### Cached Derived Reference Breaks Serialization
- **When**: An object eagerly caches a reference to an external, non-serializable resource (GUI handle, file descriptor, connection) that is fully derivable from other already-stored, serializable attributes.
- **Do**: Replace the cached attribute with a computed property that traverses the existing object graph on demand, preserving access syntax without storing the non-serializable value; prefer this over custom serialization exclusion logic that must be kept in sync.
- **Why**: Storing a derived value pulls the referenced resource's lifecycle and serializability constraints into the host object's state, when only traversal — not ownership — is needed.

### TOCTOU Race on Resource State
- **When**: A check on a resource's existence or state is separated in time from the action that depends on that state, allowing another actor to change the resource in between.
- **Do**: Use atomic check-and-act operations or acquire a lock that spans both the check and the dependent action.
- **Why**: The gap between checking and acting allows the resource's state to diverge from the assumption the action relies on.

### Cache Validity Check Before Custom Resource Loading
- **When**: A resource-loading path checks a cache but fails to account for custom or overridden loaders that may produce different results than the cached entry.
- **Do**: Include loader identity or configuration in the cache key, or invalidate the cache when the loading strategy changes.
- **Why**: The cache assumes a single canonical source, so a changed loader silently returns stale or wrong resources.

### Implicit Resource Creation Ordering
- **When**: Multiple resources have implicit creation-order dependencies (e.g., resource B assumes resource A already exists) but the orchestration does not enforce that order.
- **Do**: Make the dependency explicit — either enforce ordering in the orchestrator or have each resource declare and verify its prerequisites before creation.
- **Why**: Implicit ordering assumptions break when execution order varies across environments, concurrency levels, or configurations.

### Shared Resource Phase Coverage
- **When**: A resource is shared across multiple phases of an operation but is only set up or torn down in one phase, leaving other phases exposed to a missing or stale resource.
- **Do**: Ensure the resource's lifetime explicitly spans all phases that use it, or re-acquire it at each phase boundary.
- **Why**: Partial-phase coverage means the resource may not exist or may be invalid during phases that assume it is available.

### Capture Cleanup Capability at Acquisition Time
- **When**: The information or handle needed to properly release a resource is only available at acquisition time but is not retained, making later cleanup impossible or incomplete.
- **Do**: Capture and store the cleanup capability (handle, token, rollback info) at the moment the resource is acquired, co-locating it with the resource reference.
- **Why**: Deferred cleanup without retained context leads to leaks or partial release when the original acquisition context is no longer reachable.

### Release Exclusive State on Entity Removal
- **When**: An entity holds exclusive ownership of a shared resource (lock, unique slot, reservation) and is removed or destroyed without releasing that ownership.
- **Do**: Tie the release of exclusive state to the entity's removal path — use a finalizer, disposal hook, or the orchestrator's removal logic to guarantee release.
- **Why**: Orphaned exclusive claims block all other entities from accessing the resource indefinitely.

## Scenarios
- [serialization-boundary-for-runtime-optimized-internals](./scenarios/serialization-boundary-for-runtime-optimized-internals.md)
- [toctou-race-condition](./scenarios/toctou-race-condition.md)
- [cache-check-before-custom-resource-loading](./scenarios/cache-check-before-custom-resource-loading.md)
- [implicit-resource-creation-ordering](./scenarios/implicit-resource-creation-ordering.md)
- [shared-resource-phase-coverage](./scenarios/shared-resource-phase-coverage.md)
- [capture-cleanup-capability-at-acquisition-time](./scenarios/capture-cleanup-capability-at-acquisition-time.md)
- [release-exclusive-state-on-entity-removal](./scenarios/release-exclusive-state-on-entity-removal.md)