---
name: type-coercion
description: Bugs where implicit or explicit type conversions lose data, misroute control flow, or violate interface contracts.
---

## Overview
These bugs arise when code assumes a value will always arrive as one specific type or representation, and then converts, dispatches, or evaluates it in a way that silently corrupts data, crashes, or picks the wrong branch. The unifying cause is a mismatch between the set of types a system *actually* encounters and the set its type-handling logic *accounts for*.

## Patterns

### Scalar-vs-Collection Polymorphism
- **When**: A registration or insertion method always appends, but callers may pass either a single item or a collection of items.
- **Do**: At the lowest shared entry point, check whether the input is a collection or a single item and use extend vs. append accordingly.
- **Why**: Append-only logic silently nests collections inside collections, producing type errors when individual elements are later consumed.

### Representational Polymorphism at Validation Boundaries
- **When**: A function validates or processes a domain concept that the system allows users to express in multiple semantically equivalent forms, but only handles one.
- **Do**: Enumerate all valid representations at the entry point and branch on type to handle each correctly, rather than force-normalizing into a single form that may lose information.
- **Why**: Conflating the most common input form with the only valid form rejects or misprocesses equally legitimate alternatives the system itself supports.

### Type-Hierarchy Proxy for Structural Property
- **When**: A traversal or query uses a type-membership check as a proxy for a runtime structural property (e.g., "is a leaf") that can diverge from the class hierarchy.
- **Do**: Replace the type check with a direct structural predicate (e.g., checking whether the children collection is empty) so the condition matches the actual definition.
- **Why**: Type hierarchies encode design intent, not runtime shape; the two diverge as systems evolve, silently producing wrong results.

### Two-Valued Branch on Three-Valued Comparison
- **When**: An if/else tests equality between values that may be symbolic or unresolved, where the comparison can return a non-boolean expression object that the runtime coerces to truthy.
- **Do**: Use a comparison function that distinguishes true, false, and indeterminate, and return a deferred-evaluation representation for the indeterminate case.
- **Why**: Language truthiness rules silently collapse an unevaluated expression into a concrete branch, producing wrong concrete results for what should remain unresolved.

### Concrete-Type Gate on a Semantic Category
- **When**: A type-dispatch branch checks for one concrete type to represent a broader semantic category (e.g., "binary data"), and external sources return compatible but distinct types that implement the same protocol.
- **Do**: Extend the type check to include all types that implement the same protocol or semantic role, using the shared conversion path; prefer protocol-based checks over enumerating concrete types where possible.
- **Why**: Equating a semantic category with a single concrete type causes a lossy fallback to silently corrupt data from other compatible types.

### Incomplete Sibling-Type Coverage in Sanitization
- **When**: A preprocessing gate uses a type check against one base type to decide whether input needs sanitization, but parallel type hierarchies have sibling types representing the same conceptual role that bypass the check.
- **Do**: Extend the type check to cover all sibling types that fill the same semantic role, and add a defensive fallback that honors explicit sanitization flags for unanticipated types.
- **Why**: Type hierarchies are designed for algebraic or structural reasons, not dispatch convenience, so siblings sharing a semantic contract may live in separate inheritance branches.

### Asymmetric Operator Type Check
- **When**: A binary operator uses strict nominal typing but the operation is semantically commutative, causing one operand order to succeed and the reverse to crash.
- **Do**: Widen the type check to accept any operand satisfying the behavioral protocol (e.g., a capability flag or interface method) rather than requiring exact class membership.
- **Why**: Nominal type checks on one side and protocol-based dispatch on the other create an asymmetry that violates commutativity expectations.

### Algorithm-Specific Leaf vs. Type-System Atomicity
- **When**: A recursive algorithm uses the type system's generic "is atomic" predicate to detect leaf nodes, but composite-structured types that are semantically irreducible for the algorithm's purpose are incorrectly decomposed.
- **Do**: Extend the leaf-detection condition with algorithm-specific type checks for semantically irreducible types, rather than modifying the global atomicity property.
- **Why**: A type system's atomicity reflects general structural decomposability, not whether a specific algorithm should treat a node as a terminal — these concepts diverge as richer types are introduced.

## Scenarios
- [structured-representation-for-comparable-data](./scenarios/structured-representation-for-comparable-data.md)
- [default-representation-collision](./scenarios/default-representation-collision.md)
- [type-vs-value-validation-across-entry-points](./scenarios/type-vs-value-validation-across-entry-points.md)
- [runtime-metadata-trustworthiness](./scenarios/runtime-metadata-trustworthiness.md)
- [eager-simplification-destroys-container-invariant](./scenarios/eager-simplification-destroys-container-invariant.md)
- [pass-derived-value-not-raw-input](./scenarios/pass-derived-value-not-raw-input.md)
- [empty-collection-type-erasure-guard](./scenarios/empty-collection-type-erasure-guard.md)
- [modular-reduction-branch-cut-conflation](./scenarios/modular-reduction-branch-cut-conflation.md)
- [domain-precondition-guard](./scenarios/domain-precondition-guard.md)
- [three-valued-logic-guard](./scenarios/three-valued-logic-guard.md)
- [domain-serialization-vs-language-stringification](./scenarios/domain-serialization-vs-language-stringification.md)
- [uniform-hashability-normalization](./scenarios/uniform-hashability-normalization.md)
- [parallel-code-path-consistency](./scenarios/parallel-code-path-consistency.md)
- [truthiness-vs-type-contract](./scenarios/truthiness-vs-type-contract.md)
- [wrapper-substitutability-str-representation](./scenarios/wrapper-substitutability-str-representation.md)
- [subtype-constructor-compatibility](./scenarios/subtype-constructor-compatibility.md)
- [falsy-vs-absent-sentinel-conflation](./scenarios/falsy-vs-absent-sentinel-conflation.md)
- [proxy-to-concrete-normalization](./scenarios/proxy-to-concrete-normalization.md)
- [composite-value-serialization](./scenarios/composite-value-serialization.md)
- [conditional-postcondition-coverage](./scenarios/conditional-postcondition-coverage.md)
- [type-narrowing-at-arithmetic-boundary](./scenarios/type-narrowing-at-arithmetic-boundary.md)
- [container-preserves-element-identity](./scenarios/container-preserves-element-identity.md)
- [type-coercion-semantic-preservation](./scenarios/type-coercion-semantic-preservation.md)
- [composite-object-in-raw-payload-slot](./scenarios/composite-object-in-raw-payload-slot.md)
- [position-type-conflation](./scenarios/position-type-conflation.md)
- [sequence-element-type-preservation](./scenarios/sequence-element-type-preservation.md)
- [heterogeneous-dtype-metadata-assumption](./scenarios/heterogeneous-dtype-metadata-assumption.md)
- [type-check-before-value-compare](./scenarios/type-check-before-value-compare.md)
- [scalar-comparison-assumption](./scenarios/scalar-comparison-assumption.md)
- [abstract-type-checking](./scenarios/abstract-type-checking.md)
- [shared-utility-default-assumption](./scenarios/shared-utility-default-assumption.md)
- [structural-proxy-vs-semantic-invariant](./scenarios/structural-proxy-vs-semantic-invariant.md)
- [structural-vs-semantic-identity-in-short-circuit-optimizatio](./scenarios/structural-vs-semantic-identity-in-short-circuit-optimizatio.md)
- [fallback-path-must-preserve-type-metadata](./scenarios/fallback-path-must-preserve-type-metadata.md)
- [safe-coercion-boundary-in-operators](./scenarios/safe-coercion-boundary-in-operators.md)
- [semantic-equivalence-over-structural-equality](./scenarios/semantic-equivalence-over-structural-equality.md)
- [type-dependent-emptiness-representation](./scenarios/type-dependent-emptiness-representation.md)
- [symmetric-normalization-across-parallel-inputs](./scenarios/symmetric-normalization-across-parallel-inputs.md)
- [type-aware-coercion](./scenarios/type-aware-coercion.md)
- [domain-type-preservation-in-normalization](./scenarios/domain-type-preservation-in-normalization.md)
- [cross-environment-serialization-normalization](./scenarios/cross-environment-serialization-normalization.md)