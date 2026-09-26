---
name: general
description: Bugs from implicit assumptions, incomplete abstractions, and structural oversights across data transformation, serialization, and dispatch logic
---

## Overview
These bugs arise when code makes unstated assumptions about data shape, type coverage, or identity uniqueness that hold in common cases but break at boundaries. They share a common thread: a gap between what the developer mentally modeled and what the system actually permits.

## Patterns

### Insufficient Discriminator in Lookup
- **When**: A filter identifies an item by positive attributes, but other item types in the same collection share those attributes, causing ambiguous matches when overlapping items coexist.
- **Do**: Enumerate all distinguishing attributes—including negative discriminators that exclude non-target types—and test with overlapping items on the same keys to verify exactly one match.
- **Why**: Developers verify a filter matches the target and stop, without checking whether it also matches non-targets that share overlapping attributes.

### Invisible Character Contamination
- **When**: A format string or template contains trailing whitespace or other invisible characters that are semantically insignificant visually but break exact-match consumers (tests, linters, parsers).
- **Do**: Audit format strings using character-revealing tools (e.g., hex dump, raw representation) and strip all whitespace that serves no visual or semantic purpose, then verify against both exact-match and whitespace-enforcement consumers.
- **Why**: Developers model strings by their visual appearance, so characters invisible in rendered output are assumed not to exist.

### Recursive Formatter Bypass
- **When**: A recursive output formatter embeds sub-expressions using default string conversion instead of its own recursive dispatch, producing syntactically invalid output when sub-expressions are compound.
- **Do**: At every interpolation point, verify sub-expressions pass through the formatter's own dispatch method, and test with compound/nested sub-expressions—not just simple leaf values.
- **Why**: Developers assume certain sub-expressions are "simple enough" that their default string form is valid in the target format, but this breaks for compound expressions.

### Serialization Information Bottleneck
- **When**: A rich object is serialized into a flat dictionary containing only display-oriented scalars, discarding the source object reference that programmatic consumers need for metadata or method access.
- **Do**: Add a reference to the source object in the serialized dictionary alongside existing scalar fields, verifying no circular references or backward-compatibility breaks.
- **Why**: Developers conflate presentation data with all necessary data, assuming no consumer will need programmatic access beyond what templates render.

### Missing Behavioral Metadata in Introspection
- **When**: A listing or introspection command displays entities with only identity attributes (name, location), omitting behavioral metadata (scope, lifecycle, visibility) that affects runtime semantics.
- **Do**: Surface all attributes that change runtime behavior in the listing output, showing non-default values to reduce noise, and use distinct visual treatments for identity vs. behavioral metadata.
- **Why**: Developers building listings already know the behavioral attributes and unconsciously treat them as implementation details rather than user-facing characteristics.

### Incomplete Allowlist for Category Members
- **When**: A formatting or processing layer uses a hardcoded allowlist to gate specialized handling for members of a category, but new members are added to the domain model without updating the list, causing silent fallthrough to incorrect default handling.
- **Do**: Compare every discovered allowlist against the canonical set of members, add all missing entries, and consider deriving the list programmatically from the system's registry of known members.
- **Why**: Familiarity bias causes developers to mentally equate a category with its most common members, overlooking less-used ones that silently receive wrong default treatment.

### Fallback Format Contract Violation
- **When**: A type-dispatched formatter inherits a fallback from a parent formatter that produces output in a different format, so unhandled types silently render in the wrong format and corrupt the output tree.
- **Do**: Add a generic catch-all handler at the specialized formatter level that renders in the correct format and delegates all children back through its own dispatch, plus dedicated handlers for high-value types.
- **Why**: The set of types grows independently of the set of handlers; without a same-format fallback, any unhandled type breaks the output contract for its entire subtree.

### Incomplete Variable Rename After Copy-Paste
- **When**: Code is created by copying a sibling function and adapting variable names, but one or more references in conditionally-reached branches retain the original name, causing crashes on specific input paths.
- **Do**: On encountering an undefined-variable error resembling a nearby defined name, locate the source template, verify every rename was applied across all branches, and audit for additional missed renames.
- **Why**: Mental find-and-replace during copy-paste adaptation misses names that differ by only one or two characters, especially in branches not exercised during initial testing.

## Scenarios
- [stable-identifier-serialization](./scenarios/stable-identifier-serialization.md)
- [alias-namespace-collision-guard](./scenarios/alias-namespace-collision-guard.md)
- [filter-join-cardinality-assumption](./scenarios/filter-join-cardinality-assumption.md)
- [composite-wrapper-representation](./scenarios/composite-wrapper-representation.md)
- [uniqueness-assumption-in-code-generation](./scenarios/uniqueness-assumption-in-code-generation.md)
- [domain-restricted-pipeline-separation](./scenarios/domain-restricted-pipeline-separation.md)
- [context-dependent-escaping](./scenarios/context-dependent-escaping.md)
- [type-hierarchy-dispatch-assumption](./scenarios/type-hierarchy-dispatch-assumption.md)
- [conditional-algebraic-identity](./scenarios/conditional-algebraic-identity.md)
- [representation-sensitive-decomposition](./scenarios/representation-sensitive-decomposition.md)
- [incomplete-reduction-rules](./scenarios/incomplete-reduction-rules.md)
- [missing-discriminating-dimension-in-display](./scenarios/missing-discriminating-dimension-in-display.md)
- [algebraic-decomposition-for-code-generation](./scenarios/algebraic-decomposition-for-code-generation.md)
- [translation-layer-type-coverage](./scenarios/translation-layer-type-coverage.md)
- [self-dependency-in-decomposed-operations](./scenarios/self-dependency-in-decomposed-operations.md)
- [preserve-domain-ordering-across-formatters](./scenarios/preserve-domain-ordering-across-formatters.md)
- [trace-adjustment-through-full-pipeline](./scenarios/trace-adjustment-through-full-pipeline.md)
- [degenerate-case-syntax-disambiguation](./scenarios/degenerate-case-syntax-disambiguation.md)