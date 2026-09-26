## Problem Description

When a CLI tool encounters invalid user input (e.g., unrecognized arguments), it correctly emits a formatted, user-facing diagnostic message through its established error reporting infrastructure — but then raises an internal exception intended to halt execution. Because no caller in the chain catches this specific exception type, the raw Python traceback leaks to the end user alongside the intended error message. The result is a confusing mix of a clean diagnostic and an ugly traceback, degrading the user experience despite the error reporting system functioning correctly.

This is a **channel selection** problem: the system has two error reporting channels — a structured diagnostic message (correct) and an uncaught exception traceback (incorrect) — and both fire simultaneously. The fix is not to change *what* is reported, but to fix *how* execution terminates after the report.

## Root Cause Analysis

The underlying issue is a **leaky abstraction in control flow termination**. The internal exception is being used as a control-flow mechanism to stop execution after an error is detected, but it was never designed to be user-facing. The assumption was that some caller would catch the exception and handle it gracefully — but that assumption is violated in this code path.

The diagnostic message infrastructure is already doing the right thing: it formats the error with domain-appropriate context and presents it cleanly. The exception raised afterward serves no additional diagnostic purpose — it exists solely to halt the program. When it goes uncaught, it becomes an unintended second error reporting channel that contradicts the clean output of the first.

The principle: **an exception used purely for control-flow termination must either be guaranteed to be caught, or replaced with a termination mechanism that cannot leak** (such as `sys.exit()`).

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Users see a Python traceback when providing invalid CLI arguments, even though a properly formatted error message also appears.
  - The traceback originates from a `raise` statement that follows a diagnostic message emission call.
  - The exception type raised is internal/domain-specific and has no matching `except` handler up the call stack.
  - The crash signal is `crash-exception` combined with `incorrect-error-message` (the traceback is the "incorrect" part; the diagnostic is correct).

### 解决步骤
1. **Trace the error path**: Starting from the user-visible traceback, locate the exact `raise` statement that fires after the diagnostic message has already been emitted to the user.
2. **Verify the diagnostic message is correct**: Confirm that the line(s) immediately before the `raise` already emit a properly formatted, user-facing error message through the tool's established message/reporting infrastructure. This message should remain untouched.
3. **Replace the `raise` with a clean exit**: Substitute the `raise SomeInternalException(...)` with `sys.exit(<non-zero code>)`, using the tool's conventional error exit code (e.g., `sys.exit(32)` for configuration errors). This is a 1–2 line change at the raise site only.
4. **Preserve all surrounding infrastructure**: Do not remove the internal exception class, the diagnostic message call, or make changes to other files. The exception class may be used legitimately elsewhere; the message infrastructure is working correctly.
5. **Verify the fix**: After the change, confirm that (a) the user sees only the clean diagnostic message, (b) the process exits with a non-zero status code, and (c) no traceback is printed.

### Why This Works

The diagnostic message system is already the correct error reporting channel — it formats errors with domain-appropriate context and presents them in the expected output format. The bug is not in *what* is reported but in *what happens after* the report: an uncaught exception causes a traceback to leak.

By replacing the uncaught `raise` with `sys.exit()`, we preserve the correct error reporting channel while eliminating the broken one. The exception was only serving as a "stop execution" signal, and `sys.exit()` accomplishes the same thing without the risk of an unhandled traceback. This is the minimal, correct fix because:

- It does not change the error message content or format.
- It does not remove infrastructure that may be used elsewhere.
- It does not introduce a new error handling mechanism.
- It directly addresses the root cause: uncaught exception leaking as a traceback.

## Boundary Cases

- **Exception class used elsewhere**: The internal exception class may be legitimately raised and caught in other code paths. Do not remove or rename it — only change the specific raise site where it goes uncaught.
- **Multiple raise sites**: The same exception type may be raised in several places. Only modify the site(s) where the diagnostic message has already been emitted and the exception is demonstrably uncaught. Other sites may have proper handlers.
- **Exit code conventions**: Use the tool's established exit code for the error category (e.g., configuration error vs. runtime error). Using the wrong exit code can break CI/CD integrations that check specific codes.
- **Diagnostic message side effects**: Ensure the diagnostic message call does not depend on the exception being raised afterward (e.g., for logging or cleanup). If it does, the cleanup must be performed before `sys.exit()`.
- **Testing expectations**: Existing tests may assert that the specific exception type is raised. These tests need to be updated to check for `SystemExit` with the correct exit code and/or the presence of the diagnostic message in output.

## PR Examples

- **pylint-dev__pylint-6506**: Pylint emitted a correct `unrecognized-option` message for invalid CLI arguments but then raised an uncaught `_UnrecognizedOptionError`, causing a traceback. Fixed by replacing the `raise` with `sys.exit(32)`.