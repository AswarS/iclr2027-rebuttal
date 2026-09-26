## Problem Description

When a system accepts user-provided strings that undergo complex parsing or compilation (such as regular expressions), developers often treat these operations as simple, infallible type conversions. This leads to unhandled exceptions when users supply syntactically invalid input — for example, regex patterns using syntax from incompatible engines (e.g., PCRE's `\p{Han}` in Python's `re` module). The result is raw tracebacks leaking to end users instead of clean, actionable error messages. This pattern generalizes to any boundary where untrusted input is fed into a library-level parsing function that can raise exceptions outside the set anticipated by the surrounding framework.

## Root Cause Analysis

The underlying cause is a **cognitive misclassification of parsing operations as transparent type coercions**. Developers mentally group regex compilation (`re.compile()`) alongside trivial conversions like `int()` or `float()`, assuming the argument-parsing or configuration framework will naturally catch and report any errors. However, argument-parsing frameworks (e.g., `argparse`, custom config parsers) typically only catch a narrow set of exception types (such as `ValueError` or their own canonical error type). Regex compilation raises `re.error`, which falls outside this expected set, causing the exception to propagate uncaught up the call stack.

This is an instance of **implicit assumption violation at a trust boundary**: the developer assumes all inputs reaching the conversion function are well-formed or that failures will be caught downstream, when in reality neither guarantee holds. The problem is amplified when multiple code paths accept regex input (single values, CSV lists, etc.), as each path independently inherits the same unguarded vulnerability.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Unhandled exception tracebacks (e.g., `re.error`) surfacing to end users when they provide invalid regex patterns
  - Crash on startup or configuration load rather than a graceful validation error
  - Error messages that expose internal stack frames instead of pointing to the problematic user input
  - Bug reports citing regex syntax from other engines (PCRE, JavaScript) that users expected to work

### 解决步骤
1. **Audit all input boundaries**: Identify every code path where user-provided strings are compiled into regex patterns — including single-value converters, list/CSV argument handlers, configuration file parsers, and API inputs.
2. **Wrap compilation in targeted exception handling**: At each identified site, wrap the `re.compile()` (or equivalent) call in a `try/except` block that catches the regex engine's specific compilation error (e.g., `re.error`).
3. **Re-raise as the framework's canonical error type**: Convert the caught exception into the error type that the surrounding framework expects and handles gracefully (e.g., `argparse.ArgumentTypeError`, `ValueError`, or a custom validation exception), including the original pattern and a human-readable description of the failure.
4. **Centralize into a reusable wrapper**: Extract the error-handling logic into a single transformer/decorator function. Refactor all regex-accepting argument type converters to delegate through this wrapper, ensuring DRY compliance and consistent behavior.
5. **Add regression tests**: Write test cases using known-invalid regex patterns (e.g., `\p{Han}`, unbalanced parentheses, invalid escape sequences) to verify that the system produces a clean, user-facing error message rather than an unhandled traceback.

### Why This Works

Regex compilation is a **parsing operation on untrusted input** — it can fail in complex, unpredictable ways depending on the user's intent and the target engine's supported syntax subset. By explicitly catching the library-level exception and translating it into the framework's expected error type, we restore the contract that the framework relies on to produce consistent, user-friendly error output. Centralizing the wrapper ensures that any future regex-accepting option automatically inherits the same graceful error handling, preventing regression. This approach leverages the framework's built-in error formatting and exit behavior, producing output that is consistent with other validation failures the user already understands.

## Boundary Cases
- **Patterns valid in one regex engine but invalid in another** (e.g., PCRE Unicode property escapes `\p{...}` in Python's `re` module) — these are the most common source of user confusion and must produce a clear error, not a cryptic traceback.
- **CSV or list-valued regex arguments** where one pattern in a list is invalid — the error message should identify which specific pattern failed, not just that "the list" was bad.
- **Empty strings or whitespace-only patterns** — depending on context, these may compile successfully but produce unintended match-everything behavior; consider whether additional semantic validation is warranted.
- **Patterns that are valid but pathologically slow** (ReDoS) — exception handling alone does not address this; it is a separate concern but worth noting at the same boundary.
- **Future addition of new regex-accepting configuration options** — if the centralized wrapper is not used, new options silently reintroduce the original vulnerability.

## PR Examples
- pylint-dev__pylint-7228