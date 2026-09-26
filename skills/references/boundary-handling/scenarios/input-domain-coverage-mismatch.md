## Problem Description

This scenario describes a **capability mismatch** between a text processing component (typically a tokenizer, lexer, or parser) and the actual input domain it must handle. The processing component uses pattern-matching rules (e.g., regex character classes) that only cover a subset of the valid input space — most commonly, ASCII-only patterns applied to inputs that legitimately contain Unicode characters. This mismatch often emerges during system rewrites or migrations, where an older implementation handled the broader input domain through a different mechanism that the new architecture silently dropped.

The core pattern is: **a processing stage implicitly assumes a narrower input domain than what the system's specification actually permits**, causing valid inputs outside that narrow domain to crash, be rejected, or produce incorrect results.

## Root Cause Analysis

The underlying principle is an **implicit assumption violation** at a pipeline boundary. When a tokenizer or lexer is built with ASCII-only regex patterns like `[a-zA-Z0-9_]` or `\w` (without Unicode flags), it encodes an unstated assumption: "all valid identifiers consist only of ASCII characters." This assumption may hold for the majority of inputs, making it invisible during initial development and testing.

The problem becomes acute when:

1. **The input specification is broader than the tool's expressible domain.** The language or data format permits Unicode identifiers (e.g., Greek symbols `α`, `β`, accented characters `é`, CJK characters), but the processing regex cannot match them.
2. **A migration or rewrite removes a previously existing fallback path.** The old system may have handled non-ASCII characters through a different code path (e.g., a character-by-character scanner, a pre-processing normalization step, or a more permissive parser). The new system consolidates everything through a single regex-based tokenizer that lacks equivalent coverage.
3. **The `\w` metacharacter behaves differently across regex engines and flag configurations.** In some environments `\w` matches Unicode word characters by default; in others it is ASCII-only. Developers may not realize which behavior their environment provides.

The cognitive trap is **defaulting to the common case**: ASCII inputs work, tests pass, and the narrower character class coverage goes unnoticed until a user supplies a non-ASCII input that triggers a parse failure or exception.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Inputs containing non-ASCII characters (Unicode letters, Greek symbols, accented characters) cause **parse failures, syntax errors, or unrecognized token exceptions**.
  - Equivalent inputs using only ASCII characters work correctly — this is the key differential diagnostic.
  - The failure is a **regression** relative to an older version of the system or a different code path that previously handled these inputs.
  - Stack traces point to a tokenizer, lexer, or regex-based string decomposition stage.

### 解决步骤

1. **Locate the tokenizer/lexer stage** that decomposes input strings into tokens. Examine its regex patterns and identify all character class definitions (e.g., `[a-zA-Z]`, `\w`, `\d`, named Unicode categories).

2. **Audit character class coverage** against the input specification. Determine whether the regex uses ASCII-only ranges versus Unicode-aware character classes. Check regex compilation flags (e.g., `re.UNICODE`, `re.ASCII` in Python) that alter `\w` behavior.

3. **Choose the minimal-risk fix strategy:**
   - **Bypass approach (preferred for isolated identifiers):** Add a pre-check (e.g., `not input.isascii()`) before the ASCII-only tokenizer. When non-ASCII content is detected, route the input through an alternative path that treats it as an atomic token or uses a Unicode-aware parser. This is safer when the non-ASCII segments are typically single identifiers and extending the regex would be a large, risky change.
   - **Regex extension approach (preferred for mixed expressions):** Extend the regex to use Unicode-aware character classes (e.g., `[\w]` with Unicode flag, or explicit Unicode category escapes like `\p{L}`). This is appropriate when the tokenizer needs to decompose mixed ASCII/non-ASCII expressions containing operators and delimiters.

4. **Validate the domain boundary explicitly.** Wherever the pipeline routes input to a processing stage with limited character coverage, add an explicit domain check so that out-of-domain inputs are either handled by an alternative path or produce a clear, actionable error message rather than a cryptic parse failure.

5. **Add comprehensive test cases** covering:
   - Pure non-ASCII identifiers (e.g., `α`, `β₁`, `café`)
   - Mixed ASCII and non-ASCII in the same expression (e.g., `x + α * y`)
   - Non-ASCII characters adjacent to operators or delimiters (e.g., `(α+β)`, `f(ñ)`)
   - Regression tests for the specific inputs that triggered the original failure

### Why This Works

The fix restores alignment between the processing component's **expressible domain** and the system's **actual input domain**. The bypass approach works by recognizing that the ASCII-only tokenizer is a specialized fast path — valid and correct for its domain — and adding a guard that diverts out-of-domain inputs to a path that can handle them. This follows the principle of **explicit domain boundaries**: every processing stage should either handle the full input domain or explicitly declare and enforce its subset, with a fallback for inputs outside that subset.

The regex extension approach works by expanding the tokenizer's expressible domain to match the input domain directly, eliminating the mismatch at its source.

Both approaches convert an **implicit assumption** (inputs are ASCII) into an **explicit check**, which is the fundamental fix for implicit-assumption-violation bugs.

## Boundary Cases

- **`\w` flag ambiguity:** In Python 3, `\w` matches Unicode by default, but `re.ASCII` flag restricts it. In Python 2, `\w` was ASCII-only by default. Verify the actual behavior in your runtime environment rather than assuming.
- **Mixed-script expressions with operators:** An expression like `α*β + x` requires the tokenizer to correctly split on `*` and `+` even when identifiers are non-ASCII. A simple bypass that treats the entire string as one token will fail here.
- **Non-ASCII digits and numeric-like characters:** Characters like `²` (superscript 2) or `٣` (Arabic-Indic digit 3) may or may not be valid in the input domain. The fix should handle these according to the specification, not just "anything non-ASCII."
- **Combining characters and multi-codepoint sequences:** Characters like `é` can be represented as a single codepoint (U+00E9) or as `e` + combining acute accent (U+0065 U+0301). The tokenizer must handle both representations consistently, or a normalization step (e.g., NFC) should be applied before tokenization.
- **Empty or whitespace-only non-ASCII inputs:** Non-breaking spaces (U+00A0), zero-width joiners, and other invisible Unicode characters may pass an `isascii()` check's inverse but are not valid identifiers.
- **Performance regression from Unicode-aware regex:** Unicode-aware character classes can be significantly slower than ASCII-only ones. If the tokenizer is performance-critical, the bypass approach (fast ASCII path with Unicode fallback) may be preferable to a blanket regex extension.

## PR Examples

- **sympy__sympy-24102**: A regex-based tokenizer in SymPy's parsing pipeline used ASCII-only character classes, causing parse failures when expressions contained non-ASCII symbols (e.g., Greek letters used as mathematical variable names). The fix added a domain check to bypass the ASCII-only tokenizer for non-ASCII content.