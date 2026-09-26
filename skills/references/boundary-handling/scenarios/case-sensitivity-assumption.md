## Problem Description

A parser or processor for a file format/protocol whose specification defines certain tokens (commands, keywords, sentinel values) as case-insensitive is implemented and tested only against a narrow set of canonically-cased examples (e.g., all-uppercase tool-generated output). When users supply hand-authored or third-party-generated input using mixed-case or lowercase variants of the same tokens, the parser rejects or misinterprets them — despite the input being fully valid according to the format specification. This manifests as "unrecognized line," "invalid token," or similar errors on input that the reference tool or specification accepts without issue.

## Root Cause Analysis

The underlying cause is **implicit assumption violation driven by sample bias**. During development, the programmer encounters only one casing convention — typically the output of a canonical tool or a handful of example files — and unconsciously encodes that specific casing as the only valid form. String comparisons, regex patterns, dictionary lookups, and sentinel-value checks are all written to match the observed casing exactly, rather than the casing rules defined by the specification.

This is a contract violation: the format specification's case-insensitivity rule is part of its public contract, and the parser silently imposes a stricter invariant than the spec requires. Because the narrower invariant happens to hold for all inputs seen during development and initial testing, the bug remains latent until a user provides input that exercises the full range of valid casing permitted by the spec.

The problem is compounded when there is no single, obvious place to apply a fix — case-sensitive comparisons tend to be scattered across multiple match points (regex patterns, equality checks, dictionary lookups), making it easy to fix some while missing others.

## Solution Strategy

### 识别信号
- 观测到的现象: Crash or exception (e.g., "unrecognized line," "invalid token," "unexpected value") when processing input that uses lowercase, mixed-case, or non-canonical casing for format-defined keywords, commands, or sentinel values.
- The same input is accepted without error by the reference tool or other conforming implementations.
- The parser works correctly on tool-generated or canonical example files that happen to use a single casing convention.
- Regression appears when real-world, hand-authored, or third-party-generated files are introduced.

### 解决步骤
1. **Consult the authoritative format specification** to identify exactly which elements (commands, keywords, sentinel/missing-value markers, header tokens) are defined as case-insensitive. Do not infer casing rules from example files or tool output alone.
2. **Audit every comparison point** in the parser where tokens are matched against known values — this includes regex patterns, string equality checks (`==`, `!=`), dictionary/set lookups, `startswith`/`endswith` calls, and sentinel value comparisons. Catalog each one and determine whether it must be case-insensitive per the spec.
3. **For regex-based classification**, add the `re.IGNORECASE` flag (or equivalent) to the compiled pattern rather than normalizing input strings. This preserves the original input while matching case-insensitively.
4. **For string equality checks** against known constants (e.g., sentinel markers, command names), normalize the input value with `.upper()` or `.lower()` before comparison, or use a case-insensitive comparison helper.
5. **Prefer per-comparison-point case-insensitivity** over blanket input normalization (e.g., calling `.upper()` on the entire input line). Blanket normalization risks corrupting case-sensitive data values, comments, string fields, or metadata that the format preserves verbatim.
6. **Add comprehensive test cases** covering lowercase, uppercase, and mixed-case variants of every recognized command, keyword, and sentinel value. Include at least one test with fully non-canonical casing to prevent regression.

### Why This Works

The format specification defines a contract, and case-insensitivity of certain tokens is an explicit part of that contract. By auditing and correcting each comparison point individually, the parser is brought into conformance with the spec without introducing side effects. Targeted fixes at each match point — rather than global input transformation — ensure that case-sensitive content (data values, comments, user strings) is preserved intact, while case-insensitive tokens are matched correctly regardless of how they are cased. The added test cases encode the spec's casing rules directly into the test suite, preventing future regressions from re-introducing case-sensitive assumptions.

## Boundary Cases
- **Mixed-case within a single token** (e.g., `EnD`, `iNdEf`): Ensure comparisons handle arbitrary mixed casing, not just all-upper or all-lower.
- **Sentinel/missing-value markers in data columns**: These may appear in data payloads where blanket normalization would corrupt adjacent case-sensitive values; per-field comparison is essential.
- **Tokens that are case-insensitive in one context but case-sensitive in another**: Some formats define keywords as case-insensitive but treat data values or string literals as case-sensitive. The fix must respect this distinction.
- **Locale-sensitive casing** (e.g., Turkish İ/i): If the format spec is ASCII-based, use ASCII-safe lowering/uppering to avoid locale-dependent surprises.
- **Tokens used as dictionary keys**: If parsed tokens are stored as dictionary keys, ensure that downstream consumers also perform case-insensitive lookups, or normalize to a canonical case at storage time.

## PR Examples
- astropy__astropy-14365