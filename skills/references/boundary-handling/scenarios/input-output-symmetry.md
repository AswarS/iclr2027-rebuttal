## Problem Description

When a system has separate input parsing and output serialization paths, an asymmetry can emerge where the system's internal model supports more variants than the parser can recognize. This manifests as a **round-trip failure**: the system constructs an object, serializes it to a string representation, but that string cannot be parsed back into an equivalent object. Users encounter confusing errors when they copy-paste system-generated output as input, or when programmatic workflows feed serialized representations back through the parser.

This pattern is especially common in systems with string-based specification languages (DSLs, domain descriptors, configuration strings) where a regex or conditional dispatch chain enumerates "known" input categories, but the internal object model has grown beyond what the parser was originally designed to handle.

## Root Cause Analysis

The fundamental cause is **enumeration completeness bias** — a cognitive trap where the developer builds a parser against a known set of cases and mentally marks it as "complete," without accounting for the fact that the system's internal capabilities extend beyond the originally anticipated use cases.

The asymmetry arises because:

1. **Parsers are written enumeratively** — they list known valid inputs via regex alternatives, switch cases, or if/elif chains. Adding a new internal variant requires explicitly updating the parser.
2. **Serializers are written generically** — they dispatch on the actual runtime type or state of an object, so they naturally cover all variants the system can construct, including ones added after the parser was written.
3. **The two paths are maintained independently** — there is no structural coupling or automated check ensuring that every serializable form is also parseable.

A secondary contributing factor is the use of an if/elif/else dispatch pattern where the `else` branch implicitly handles "the last valid option." This is only safe when the upstream recognition pattern (e.g., regex) constrains inputs to exactly the valid set. If the regex is extended without updating the dispatch, or vice versa, the coupling breaks silently.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Crash/exception on edge case**: A parser raises an error (e.g., `ValueError`, `SyntaxError`, regex match failure) when given a string that was produced by the system's own `__repr__`, `__str__`, or serialization method.
  - **Regression on edge case**: A previously working workflow breaks when a new internal variant is added to the object model but the parser is not updated.
  - **Copy-paste failure**: A user copies a system-displayed representation and pastes it as input, only to receive an unexpected error.

### 解决步骤
1. **Enumerate the full internal model**: Catalog all ground types, base variants, or categories that the system can construct programmatically. This includes variants added over time that may not have been part of the original design.
2. **Audit the parser's recognition surface**: Extract the regex patterns, switch cases, or if/elif chains that gate input recognition. Map each branch to the internal variant it constructs.
3. **Identify gaps**: Diff the two sets — find internal variants that have no corresponding parser branch. These are the round-trip failures.
4. **Extend recognition and dispatch together**: For each missing category, add it to both the recognition pattern (e.g., new regex alternative) AND the corresponding construction/dispatch branch. Treat these as an atomic unit of change.
5. **Verify round-trip symmetry**: For every object the system can produce, serialize it to string form, parse that string back, and assert equivalence. Encode this as a test.
6. **Document intentional exclusions**: If certain combinations are logically or mathematically invalid (e.g., a fraction field over an approximate domain), explicitly document why they are excluded rather than silently omitting them from the parser.

### Why This Works

By treating the parser and serializer as two halves of a **bijective contract**, the fix ensures that the system's input and output surfaces are symmetric. Enumerating from the internal model outward (rather than from the parser inward) guarantees completeness, because the internal model is the source of truth for what the system can represent. Adding round-trip tests creates a structural coupling that prevents future regressions when new variants are introduced.

## Boundary Cases
- **Newly added internal variants**: Any time a new type or category is added to the internal model, the parser must be updated simultaneously — this should be enforced by round-trip tests.
- **Intentionally invalid combinations**: Some serializable forms may represent states that should not be user-constructible (e.g., intermediate computation artifacts). These need explicit validation with clear error messages, not silent parser omission.
- **Ambiguous string representations**: If two distinct internal objects serialize to the same string, the parser cannot distinguish them — serialization must be injective for round-trip to work.
- **Nested or composed specifications**: When specifications can be nested (e.g., `QQ[x][y]` or `RR(x,y)`), the parser must handle recursive structure, and each level must independently satisfy round-trip symmetry.
- **Whitespace, casing, and formatting variations**: The parser should be tolerant of cosmetic differences in strings that the serializer might produce across versions or configurations.

## PR Examples
- **sympy__sympy-14396**: The SymPy polynomial domain system could internally construct domains over approximate ground fields (e.g., `RR[x]`, `CC[x,y]`), and their `__str__` produced valid-looking domain strings. However, the `sympy.polys.polytools.Domain.preprocess` parser's regex and dispatch logic only recognized exact/algebraic ground fields (`ZZ`, `QQ`, `EX`), causing a crash when parsing system-generated domain strings for real or complex coefficient rings.