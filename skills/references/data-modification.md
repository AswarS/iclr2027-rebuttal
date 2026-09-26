---
name: data-modification
description: Bugs where data is transformed incorrectly, partially, or silently not transformed when it should be.
---

## Overview

This category covers bugs where a data transformation operation fails to correctly modify all relevant parts of the data. The common thread is a gap between the intended transformation and what actually gets applied — whether due to missed substructures, duplicate application, discarded results, leaked mutation, or inconsistent output shape.

## Patterns

### Shallow Transformation of Recursive Structures
- **When**: A transformation is applied to a data structure that contains nested or recursive instances of itself (e.g., trees, nested objects, recursive types).
- **Do**: Verify that the transformation recurses into all substructures, not just the top level. Ensure every node or element that matches the transformation criteria is visited and modified.
- **Why**: The transformation logic handles the immediate level but fails to descend into children, leaving nested instances unchanged.

### Double Transformation in Multi-Stage Pipelines
- **When**: A transformation (escaping, encoding, normalization) is applied at one stage of a pipeline, and a downstream stage conditionally applies the same transformation again, producing corruption only under certain configurations.
- **Do**: Trace the full pipeline from source to final output, identify every stage that applies the same transformation, and ensure exactly one stage owns it for any given configuration path — gating earlier stages on the same conditions that control later ones. Add tests covering the matrix of configuration states.
- **Why**: Each stage assumes it is the sole transformer, but no stage checks whether the input has already been transformed, and configuration variance makes the duplication appear only in some paths.

### Discarded Return Value on Copy-Returning Methods
- **When**: A transformation method is called as a bare statement on a string-like or immutable-style object without capturing or assigning back its return value.
- **Do**: Audit standalone method calls on string-like or array-like objects for missing assignment; verify whether the method mutates in place or returns a new object, and assign the result back — using slice assignment when writing into a shared buffer.
- **Why**: The method follows a functional contract (returns a new object), but the caller assumes in-place mutation because the surrounding container is mutable, silently discarding the transformed result.

### Yielding Mutable State Across an API Boundary
- **When**: A generator or iterator yields a mutable container that it continues to mutate internally after yielding, and consumers collect multiple yielded values into a list or compare them.
- **Do**: Copy the mutable object at the yield point so each emitted value is independent; add tests that materialize all outputs into a collection and verify they are distinct objects with correct values.
- **Why**: Yield transfers a reference, not a value; continued mutation aliases all previously yielded references to the final state, violating the consumer's expectation of independent values.

### Input Deduplication for Idempotent Operations
- **When**: An operation with mathematical idempotency or commutativity (e.g., set intersection, min/max, logical AND/OR) accepts variable arguments and uses pairwise reduction, but duplicate operands produce incorrect results.
- **Do**: Deduplicate and canonically order the argument list at the entry point — before any reduction logic — using semantic equality, not just reference identity. Test with duplicate operands and verify the result matches the single-operand case.
- **Why**: Pairwise reduction algorithms can reach incorrect intermediate states when processing redundant copies of an operand that should be semantically transparent.

### Partial Field Transformation
- **When**: A transformation targets a subset of fields in a record or object, but the data model has grown or contains optional fields.
- **Do**: Audit all fields that should be affected by the transformation, looking for newly added or conditional fields that the transformation logic doesn't account for.
- **Why**: The transformation was written against an earlier or incomplete view of the data model, leaving some fields stale or inconsistent.

### Copy-Then-Mutate Divergence
- **When**: Data is copied (cloned, serialized, or projected) and then the copy is modified independently.
- **Do**: Check whether the copy is shallow when it should be deep, or whether mutations to the copy inadvertently affect the original (or vice versa); confirm the copy captures all relevant state before mutation begins.
- **Why**: A shallow copy shares references with the original, so modifications propagate unexpectedly or fail to propagate when they should.

### Incorrect Mapping or Conversion Logic
- **When**: Data is converted from one representation to another (e.g., unit conversion, format change, encoding).
- **Do**: Validate the conversion formula or mapping table against the specification; test with boundary values and representative samples from both ends of the domain.
- **Why**: The conversion logic contains an error in its formula, lookup, or ordering that produces plausible but incorrect results.

### Key-Existence Side Effects in Accumulators
- **When**: Multiple execution paths contribute to a shared dictionary-based counter or accumulator, and some paths unconditionally record identity values (zero, empty) while others skip recording, causing the output's key structure to vary by code path rather than by semantic outcome.
- **Do**: Guard each accumulation step so it only writes when the contribution is semantically meaningful; define a single canonical representation for "nothing happened" and ensure all paths converge to it.
- **Why**: Inserting a zero-valued key into a dictionary changes the container's observable structure, conflating "recorded a zero" with "recorded nothing" and breaking output symmetry across logically equivalent inputs.

### Silent No-Op on Unrecognized Input
- **When**: A transformation function receives input that doesn't match its expected shape or type.
- **Do**: Check whether the function silently returns input unchanged when it should either transform it or signal an error; add explicit handling or validation for unexpected variants.
- **Why**: Permissive pass-through logic masks cases where data should have been transformed but wasn't, producing silently incorrect output.

## Scenarios
- [preserve-recursive-substructure](./scenarios/preserve-recursive-substructure.md)
- [fold-over-non-associative-operation](./scenarios/fold-over-non-associative-operation.md)
- [idempotent-data-migration](./scenarios/idempotent-data-migration.md)
- [preserve-explicit-configuration-in-normalization](./scenarios/preserve-explicit-configuration-in-normalization.md)
- [multi-source-dedup-collection](./scenarios/multi-source-dedup-collection.md)
- [cleanup-mechanism-coverage-mismatch](./scenarios/cleanup-mechanism-coverage-mismatch.md)
- [sign-ambiguity-canonicalization](./scenarios/sign-ambiguity-canonicalization.md)
- [output-structure-preservation-assumption](./scenarios/output-structure-preservation-assumption.md)
- [yield-point-mutation-vulnerability](./scenarios/yield-point-mutation-vulnerability.md)
- [semantic-vs-syntactic-equivalence-normalization](./scenarios/semantic-vs-syntactic-equivalence-normalization.md)
- [composite-propagation](./scenarios/composite-propagation.md)
- [key-existence-vs-value-semantics](./scenarios/key-existence-vs-value-semantics.md)
- [recognize-equivalent-operations-need-equivalent-safeguards](./scenarios/recognize-equivalent-operations-need-equivalent-safeguards.md)
- [decomposition-reaggregation-mismatch](./scenarios/decomposition-reaggregation-mismatch.md)
- [container-capacity-mismatch](./scenarios/container-capacity-mismatch.md)