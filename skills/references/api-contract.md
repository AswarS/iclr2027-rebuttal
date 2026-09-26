---
name: api-contract
description: Bugs where code violates, assumes incorrect, or incompletely implements contracts of APIs, protocols, data structures, or interfaces
---

## Overview

This category covers bugs arising from mismatches between what code expects and what an interface actually specifies, supports, or guarantees. The common thread is a divergence between the assumed contract and the real one — whether the contract is explicit (a specification, schema, or type protocol) or implicit (behavioral conventions, paired method obligations, or compositional invariants).

## Patterns

### Incomplete Protocol Implementation
- **When**: A type implements part of a protocol bundle (e.g., equality without hashing, indexing without length, forward operator without reverse) and consumers invoke the missing half, or a subclass overrides a method without replicating the parent's implicit behavioral guards and preconditions.
- **Do**: Enumerate all methods in the protocol bundle and all implicit contracts (guards, preconditions, metadata attributes) of overridden methods; implement the full minimal coherent subset; ensure paired methods are symmetric and consistent; when overriding, replicate or delegate to the parent's precondition checks before adding new logic.
- **Why**: Protocols are bundles of cooperating methods and implicit obligations — implementing one half creates a promise that the other half exists, and consumers or runtimes depend on that promise.

### Composite Capability Mismatch
- **When**: A composite object (union, wrapper, collection) inherits or exposes the full interface of its components, but some operations are semantically invalid, silently incorrect, or produce misleading results (such as a one-to-one property arbitrarily selecting the first element of a multi-element group).
- **Do**: Audit every public method and property against the composite's actual capabilities; guard unsupported operations with explicit errors rather than allowing silent partial application; override properties that assume a one-to-one relationship to return an explicit "not applicable" value when the composite breaks that assumption.
- **Why**: Composites inherit interface surface area that exceeds their semantic capabilities, and silent acceptance of invalid operations or arbitrary representative selection is worse than a loud failure or explicit opt-out.

### Proxy Metadata and Substitution Gap
- **When**: A proxy, wrapper, or adapter satisfies the behavioral contract of the object it replaces but lacks metadata attributes, structural properties, or faithful string representations that downstream consumers introspect — or its string conversion serves a diagnostic purpose that diverges from the wrapped object's semantics.
- **Do**: Identify all metadata attributes and standard protocol methods the original object's type contract implies; copy or delegate them onto the proxy using standard transfer utilities; ensure `__str__`/`__repr__` either faithfully proxy the wrapped value or are removed in favor of explicit diagnostic methods.
- **Why**: Substitution requires satisfying both the behavioral protocol and the structural/metadata protocol — consumers treat objects as rich entities, not just invocation targets.

### Convenience Layer Parameter Gap
- **When**: A higher-level wrapper maps user-facing configuration to a lower-level system's parameters, but some supported lower-level parameters have no first-class mapping, are hardcoded internally, or are silently overridden by explicit arguments that shadow caller-provided values in forwarded kwargs.
- **Do**: Enumerate all parameters the lower layer accepts; compare against the wrapper's explicit surface; add first-class mappings for missing parameters; replace hardcoded values with defaulting patterns (e.g., `setdefault`) that respect caller-provided overrides; expose internal strategy choices as defaulted parameters accepting both static values and callables for deferred resolution.
- **Why**: Incomplete enumeration and silent overrides break the wrapper's implicit contract of completeness and configurability, forcing users into less discoverable workarounds.

### Validation-Execution Divergence
- **When**: A validation check uses a stricter, looser, or different acceptance criterion than the runtime system that actually consumes the value — including over-generalized restrictions applied uniformly across modes where only a subset is genuinely constrained, or new API paths that omit validations an equivalent older path enforces.
- **Do**: Replace independent validation logic with delegation to the actual runtime resolution function; narrow restrictions to fire only for the mode where the constraint genuinely applies; when introducing parallel APIs, inventory all validations from the existing path and carry forward every domain-intrinsic invariant.
- **Why**: Validation and execution must share the same definition of "valid" — divergence produces either false-positive rejections or silent acceptance of invalid inputs.

### Context-Dependent Identity
- **When**: An object's equality and hashing use only an intrinsic identifier that was unique at definition time, but structural copying or inheritance into multiple contexts creates distinct objects sharing the same identifier, or a wrapper overrides equality without providing a corresponding hash.
- **Do**: Include both the intrinsic identifier and the owning context in equality and hash computations; handle the unbound/pre-assignment state gracefully; always pair `__eq__` with `__hash__` delegating to the same data; implement value-based equality for objects that represent structured data with multiple internal representations.
- **Why**: Identity is context-dependent when objects can exist in multiple containers, and the language contract requires that objects comparing as equal produce identical hashes.

### Silent Parameter Discard
- **When**: An API accepts optional or extensible parameters but certain values are silently ignored — because a hardcoded value overrides them, a dependent companion parameter is absent, or the parameter only applies to a subset of internal modes — and no runtime enforcement exists for parameter co-occurrence constraints.
- **Do**: Add explicit validation that rejects dependent parameters when their companion is absent; raise hard errors for parameter combinations that have zero effect; ensure forwarded kwargs are not shadowed by explicit arguments; prefer outright rejection over warnings for silent no-ops.
- **Why**: Silent no-ops violate the principle of least surprise — users believe their configuration is applied when it is not, creating subtle bugs that are hard to diagnose.

### Cooperative Protocol Chain Break
- **When**: A new class is inserted into an inheritance hierarchy that uses a cooperative opt-in protocol (e.g., memory layout declarations, metaclass hooks) but the new class omits the required declaration, or a framework auto-generates members that unconditionally overwrite user-defined overrides without checking for existing definitions.
- **Do**: Inspect the full resolution order for cooperative protocols and ensure every class explicitly declares participation, even if empty; guard auto-generated assignments with MRO-aware existence checks so user-defined members take priority; add regression tests verifying protocol invariants on representative instances.
- **Why**: Cooperative protocols require unanimous participation — silence is not neutral but an active opt-out that overrides all descendants' declarations — and user-defined code should have higher priority than framework-generated defaults.

### Specification Compliance Gap
- **When**: Implementing an output format defined by an external specification, or a family of components serving the same conceptual role, where some required fields, methods, or attributes are missing because the implementation was built to satisfy the producer's own needs rather than systematically auditing the target contract.
- **Do**: Obtain the canonical specification or interface contract; enumerate every required element and cross-reference against the current implementation; surface already-computed internal state rather than re-running computation; implement missing interface elements by delegating richer methods to simpler ones to avoid code duplication.
- **Why**: An output format or interface role is a contract with consumers — partial implementation creates silent interoperability failures or forces consumers to write adapter code for components that should be interchangeable.

### Structural Query vs. Re-parsing
- **When**: A function determines a semantic property of a structured object by extracting a raw subcomponent and passing it through a general-purpose parser, or checks type membership via collection identity rather than inheritance-aware predicates, or uses a single common-name attribute for duck-type protocol detection that collides with unrelated user-defined attributes.
- **Do**: Replace string-parsing approaches with the object's own algebraic or structural query API; use inheritance-aware checks (`issubclass`/`isinstance`) instead of collection membership for type predicates; add secondary discriminator checks using canonical marker attributes unique to the protocol before inspecting ambiguous attributes.
- **Why**: Structured objects provide dedicated query interfaces that handle arbitrary content safely, type hierarchies are not flat enumerations, and single common-name duck-type checks are inherently fragile against namespace collisions.

## Scenarios
- [hardcoded-structural-positions-from-assumed-configuration](./scenarios/hardcoded-structural-positions-from-assumed-configuration.md)
- [reflected-operator-protocol-awareness](./scenarios/reflected-operator-protocol-awareness.md)
- [non-invertible-interface-fallback](./scenarios/non-invertible-interface-fallback.md)
- [closed-type-dispatch-to-open-protocol](./scenarios/closed-type-dispatch-to-open-protocol.md)
- [derived-class-interface-completeness](./scenarios/derived-class-interface-completeness.md)
- [extensible-dispatch-registry-completeness](./scenarios/extensible-dispatch-registry-completeness.md)
- [dispatch-interface-conformance](./scenarios/dispatch-interface-conformance.md)
- [grammar-optionality-nesting](./scenarios/grammar-optionality-nesting.md)
- [qualified-vs-simple-name-assumption](./scenarios/qualified-vs-simple-name-assumption.md)
- [exec-namespace-scoping](./scenarios/exec-namespace-scoping.md)
- [hidden-serialization-contract-in-cloning](./scenarios/hidden-serialization-contract-in-cloning.md)
- [non-interactive-widget-label-contract](./scenarios/non-interactive-widget-label-contract.md)
- [coincidental-dependency-assumption](./scenarios/coincidental-dependency-assumption.md)
- [namespace-instance-context-propagation](./scenarios/namespace-instance-context-propagation.md)
- [relative-path-access-pattern-assumption](./scenarios/relative-path-access-pattern-assumption.md)
- [bidirectional-relation-identity-normalization](./scenarios/bidirectional-relation-identity-normalization.md)
- [qualified-vs-simple-name-in-serialization](./scenarios/qualified-vs-simple-name-in-serialization.md)
- [polymorphic-interface-assumption](./scenarios/polymorphic-interface-assumption.md)
- [repr-protocol-compliance-with-delegated-storage](./scenarios/repr-protocol-compliance-with-delegated-storage.md)
- [aggregate-operator-selection](./scenarios/aggregate-operator-selection.md)
- [convergence-exit-conflation](./scenarios/convergence-exit-conflation.md)
- [empty-input-boundary-guard](./scenarios/empty-input-boundary-guard.md)
- [output-structure-consumer-convention-mismatch](./scenarios/output-structure-consumer-convention-mismatch.md)
- [context-dependent-sentinel-translation](./scenarios/context-dependent-sentinel-translation.md)
- [input-contract-mismatch-sanitization](./scenarios/input-contract-mismatch-sanitization.md)
- [precondition-vs-symptom-validation](./scenarios/precondition-vs-symptom-validation.md)
- [property-based-over-type-based-checking](./scenarios/property-based-over-type-based-checking.md)
- [decorated-delegation-leakage](./scenarios/decorated-delegation-leakage.md)