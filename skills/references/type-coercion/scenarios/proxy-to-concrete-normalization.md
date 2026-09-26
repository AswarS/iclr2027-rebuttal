## Problem Description

When a system traverses chains of related model or type references (e.g., following foreign key paths in a query builder), it may encounter **proxy types** — lightweight wrappers or aliases that delegate their physical storage schema to a concrete parent type. If the system attempts to resolve physical field metadata (column names, primary keys, initialized field lists) directly on the proxy type's metadata rather than first normalizing to the concrete (storage-owning) type, it will fail with crashes, "value not found" errors, or incorrect field resolution. This pattern manifests most acutely when combining field-narrowing operations (e.g., `only()`, `defer()`) with eager-loading of related objects (e.g., `select_related()`) through proxy type relationships.

## Root Cause Analysis

Proxy types are an intentional abstraction layer: they share the storage schema of a concrete parent but carry their own (potentially incomplete) metadata representation. The root cause is an **implicit assumption** that every model class obtained from a relationship descriptor is a fully self-describing, database-backed entity. This assumption holds for concrete models but breaks for proxy models, whose metadata objects may not directly enumerate physical database columns or primary key attributes.

The deeper principle at play is **incomplete abstraction normalization**: when a system has multiple representations for the same underlying entity (proxy vs. concrete), any code path that needs to interact with the physical/storage layer must first canonicalize to the concrete representation. Failure to do so allows a variant (proxy) representation to propagate into logic that was only designed for the canonical (concrete) form, causing downstream resolution failures.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - A crash or `KeyError`/`ValueError` when looking up a primary key or physical column in a field metadata list
  - The error occurs specifically when combining eager-loading (`select_related`) with field-narrowing (`only`/`defer`) where the relationship target is a proxy type
  - The failure is a **regression on edge case** — standard concrete model paths work fine; only proxy model traversals break
  - Stack traces point to deferred-field or column-selection logic attempting to access metadata that doesn't exist on the proxy type

### 解决步骤
1. **Audit relationship traversal points**: Identify every location in the deferred-field or column-selection logic where a model class is obtained by following a relationship descriptor (foreign key, one-to-one, generic relation, etc.).
2. **Insert early canonicalization**: Immediately after obtaining the referenced model class, normalize it to its concrete (storage-owning) counterpart (e.g., `model = model._meta.concrete_model` or equivalent). Apply this on the model reference variable itself, not on downstream metadata accessors.
3. **Verify downstream consistency**: Confirm that all subsequent logic — field enumeration, primary key resolution, init-list construction — now consistently operates on the concrete model without requiring additional normalization.
4. **Add targeted test coverage**: Write tests for query paths that combine eager-loading with field-narrowing where the relationship target is a proxy type, including multi-level proxy chains and mixed concrete/proxy traversals.

### Why This Works

This follows the principle of **early canonicalization**: convert variant representations to a single canonical form at the earliest possible point of entry. By normalizing the model reference at the moment it is obtained from a relationship descriptor — rather than scattering normalization across every downstream consumer — we:

- **Prevent inconsistency propagation**: No downstream code ever sees a proxy type where it expects a concrete type.
- **Reduce fix surface area**: A single normalization point is easier to maintain and audit than multiple scattered checks.
- **Respect the abstraction contract**: Proxy types are meant to be transparent at the storage layer; normalizing to concrete enforces this contract explicitly rather than relying on implicit assumptions.

## Boundary Cases
- **Multi-level proxy chains**: A proxy of a proxy of a concrete model — normalization must resolve all the way to the root concrete model, not just one level up.
- **Proxy models with overridden managers or querysets**: The concrete model normalization should only affect physical field resolution; proxy-specific manager behavior should be preserved in non-storage contexts.
- **Abstract base classes in the chain**: Abstract models are not concrete models; the normalization must skip abstract parents and find the actual storage-owning concrete model.
- **Multi-table inheritance mixed with proxies**: A proxy of a child in a multi-table inheritance hierarchy should resolve to the child's concrete model, not the parent's.
- **`select_related` through multiple proxy hops**: Chains like `A → ProxyB → ProxyC` where both B and C are proxies of different concrete models must each be independently normalized.
- **`only()`/`defer()` targeting fields defined on the proxy**: If a proxy re-declares or aliases fields, the normalization must still correctly map to the concrete model's physical columns.

## PR Examples
- django__django-15814