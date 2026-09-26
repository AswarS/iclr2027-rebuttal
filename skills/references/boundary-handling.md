---
name: boundary-handling
description: Bugs at input boundaries, edge cases, interface mismatches, or assumptions about data format, range, and structure.
---

## Overview

Boundary-handling bugs arise when code makes implicit assumptions about the shape, format, range, encoding, or structure of inputs at system boundaries. They manifest when real-world data violates those assumptions — at API edges, user input, file parsing, type coercion, configuration surfaces, or inter-component interfaces.

## Patterns

### Case Sensitivity Assumption
- **When**: Code compares, matches, or indexes strings assuming a specific casing but receives mixed-case input from an external source.
- **Do**: Normalize both sides of any comparison to a canonical case before matching. Audit all string-keyed lookups and comparisons at input boundaries.
- **Why**: Different producers of the same data may use different casing conventions, and the consuming code silently fails to match.

### Off-By-One / Temporal Drift at Range Edges
- **When**: Code processes sequences with inclusive-vs-exclusive bound confusion, or uses a hardcoded pivot (e.g., a two-digit year cutoff) derived from a specification that defines a sliding window relative to the current time.
- **Do**: Test first, last, and empty inputs for every range. When a specification defines a temporally relative boundary, compute the pivot dynamically from the current context rather than hardcoding a snapshot.
- **Why**: Misinterpreting bound inclusivity or freezing a time-relative rule into a static constant causes silent misclassification that worsens over time.

### Null / Empty Input Conflation
- **When**: Code treats null, empty string, zero, empty collection, or "missing" as interchangeable, or uses a blanket emptiness check on a structure with multiple independent dimensions (e.g., a 0×N matrix treated the same as 0×0).
- **Do**: Distinguish "absent" from "present but empty" at every boundary; for multi-dimensional structures, check each dimension independently and preserve non-zero dimensional metadata through operations.
- **Why**: Collapsing distinct degenerate states into one equivalence class silently discards dimensional metadata or misroutes data through identity-element fast paths.

### Type Coercion at Interface
- **When**: Data crosses a boundary that silently coerces types (e.g., string↔number, int↔float, truthy/falsy).
- **Do**: Validate and explicitly convert types immediately at the boundary. Never rely on implicit coercion for correctness.
- **Why**: Implicit coercion can truncate, round, or reinterpret values in ways that violate downstream invariants.

### Normalization-Before-Derivation Ordering
- **When**: A pipeline extracts a meaningful component from user input (e.g., a name from a path) and then validates it, but the extraction implicitly depends on the input being in canonical form while normalization happens later or not at all.
- **Do**: Reorder the pipeline so normalization (trimming, deduplicating separators, resolving canonical form) runs before any derivation step that depends on canonical input; prefer standard library normalization over manual character stripping.
- **Why**: Users and tooling routinely produce non-canonical input, and any derivation step that assumes canonical form must run after the step that establishes it.

### Cross-Property Configuration Inconsistency
- **When**: A configuration surface allows two or more properties validated independently but with an implicit mutual dependency (e.g., a size constraint and an enumeration of allowed values that must fit within that size).
- **Do**: After each property passes its own structural validation, perform a cross-property consistency check that verifies the combined invariant and emit a hard error when the inconsistency guarantees a runtime failure.
- **Why**: Properties that appear independent often have implicit joint invariants; validating each in isolation creates a false sense of correctness that only surfaces as runtime failure or silent data corruption.

### Overly Strict Structural Homogeneity Check
- **When**: A combining operation (concatenation, merge, union) enforces that all inputs share the exact same structure, but the downstream processing logic already handles partial or heterogeneous inputs naturally.
- **Do**: Examine whether the downstream logic tolerates partial presence; if so, relax the upstream validation to allow the union of all input schemas, skipping missing fields per item rather than rejecting the entire operation.
- **Why**: Combining operations naturally map to outer-join semantics; enforcing inner-join strictness at the validation layer blocks legitimate heterogeneous inputs the core algorithm already supports.

### Approximate Solver in Exact Domain
- **When**: A system uses an approximate method (least-squares, best-fit) to solve equations in a domain where only exact solutions are semantically valid (e.g., unit conversion, symbolic rewriting, dimensional analysis).
- **Do**: Replace approximate solvers with exact methods that fail explicitly when no solution exists; on failure, return a sentinel or fall back to safe default behavior rather than producing a "closest" answer.
- **Why**: In discrete or symbolic domains, an approximate solution to an inconsistent system is not a degraded result — it is a fundamentally wrong result that violates domain invariants.

### Delimiter / Escape Handling
- **When**: Code splits, joins, or escapes strings assuming delimiters or special characters won't appear in the data itself.
- **Do**: Use proper escaping or structured formats. Test with inputs containing the delimiter and escape character themselves.
- **Why**: Unescaped delimiters in data cause mis-parsing, field shifting, or injection.

### Unvalidated External Format
- **When**: Code parses external input (files, network payloads, environment variables) assuming a specific structure or encoding.
- **Do**: Validate structure and encoding before processing. Fail explicitly on unexpected formats rather than propagating corrupt data.
- **Why**: External sources are not bound by internal invariants, and malformed input silently corrupts downstream state.

## Scenarios
- [case-sensitivity-assumption](./scenarios/case-sensitivity-assumption.md)
- [parameter-merge-precedence](./scenarios/parameter-merge-precedence.md)
- [alias-equivalence-in-guard-conditions](./scenarios/alias-equivalence-in-guard-conditions.md)
- [existence-vs-type-check-conflation](./scenarios/existence-vs-type-check-conflation.md)
- [indeterminate-as-true-fallacy](./scenarios/indeterminate-as-true-fallacy.md)
- [boundary-value-handling-in-discrete-functions](./scenarios/boundary-value-handling-in-discrete-functions.md)
- [boundary-blindness-zero-element](./scenarios/boundary-blindness-zero-element.md)
- [composite-domain-decomposition](./scenarios/composite-domain-decomposition.md)
- [cross-product-edge-case-enumeration](./scenarios/cross-product-edge-case-enumeration.md)
- [namespace-partitioning-awareness](./scenarios/namespace-partitioning-awareness.md)
- [canonicalize-before-pattern-matching](./scenarios/canonicalize-before-pattern-matching.md)
- [regex-multiline-assumption](./scenarios/regex-multiline-assumption.md)
- [regex-anchor-semantics](./scenarios/regex-anchor-semantics.md)
- [platform-specified-exception-to-guard-clause](./scenarios/platform-specified-exception-to-guard-clause.md)
- [untrusted-runtime-data-assumption](./scenarios/untrusted-runtime-data-assumption.md)
- [path-traversal-variable-staleness](./scenarios/path-traversal-variable-staleness.md)
- [inherited-vs-originated-property-distinction](./scenarios/inherited-vs-originated-property-distinction.md)
- [input-precondition-guard](./scenarios/input-precondition-guard.md)
- [empty-collection-aggregation-guard](./scenarios/empty-collection-aggregation-guard.md)
- [post-loop-accumulator-guard](./scenarios/post-loop-accumulator-guard.md)
- [missing-key-fallback-assumption](./scenarios/missing-key-fallback-assumption.md)
- [boundary-assertion-character-class-assumption](./scenarios/boundary-assertion-character-class-assumption.md)
- [regex-grammar-alignment](./scenarios/regex-grammar-alignment.md)
- [cross-domain-identifier-validity](./scenarios/cross-domain-identifier-validity.md)
- [upstream-representation-shift-boundary-gap](./scenarios/upstream-representation-shift-boundary-gap.md)
- [zero-divisor-guard-for-degenerate-results](./scenarios/zero-divisor-guard-for-degenerate-results.md)
- [syntax-ambiguity-in-pattern-matching](./scenarios/syntax-ambiguity-in-pattern-matching.md)
- [in-band-sentinel-partitioning](./scenarios/in-band-sentinel-partitioning.md)
- [character-role-conflation-in-grammar](./scenarios/character-role-conflation-in-grammar.md)
- [dimension-bound-clamping](./scenarios/dimension-bound-clamping.md)
- [domain-constraint-completeness](./scenarios/domain-constraint-completeness.md)
- [boundary-vs-offset-conflation](./scenarios/boundary-vs-offset-conflation.md)
- [algebraic-identity-precondition-guard](./scenarios/algebraic-identity-precondition-guard.md)
- [uniform-structure-assumption-in-2d-layout](./scenarios/uniform-structure-assumption-in-2d-layout.md)
- [glyph-proportion-redistribution](./scenarios/glyph-proportion-redistribution.md)
- [empty-collection-base-case](./scenarios/empty-collection-base-case.md)
- [first-match-vs-last-match-in-repeated-delimiters](./scenarios/first-match-vs-last-match-in-repeated-delimiters.md)
- [input-domain-coverage-mismatch](./scenarios/input-domain-coverage-mismatch.md)
- [ambiguous-null-negation](./scenarios/ambiguous-null-negation.md)
- [heterogeneous-container-recursion](./scenarios/heterogeneous-container-recursion.md)
- [incomplete-type-enumeration-in-guard](./scenarios/incomplete-type-enumeration-in-guard.md)
- [pipeline-boundary-cleanup-ordering](./scenarios/pipeline-boundary-cleanup-ordering.md)
- [cli-argument-ordering-semantics](./scenarios/cli-argument-ordering-semantics.md)
- [input-output-symmetry](./scenarios/input-output-symmetry.md)
- [bound-tightness-as-performance-parameter](./scenarios/bound-tightness-as-performance-parameter.md)