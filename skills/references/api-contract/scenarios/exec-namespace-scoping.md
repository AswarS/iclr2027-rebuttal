## Problem Description

When dynamically evaluating code strings via `exec()` from within a function body, nested callables (functions, classes) defined in the evaluated code fail to resolve names that were bound at the top level of the same evaluated string. This manifests as unexpected `NameError` exceptions for imports, variables, or other bindings that appear correctly defined in the evaluated code. The issue is specific to `exec()` calls made inside function scopes without explicit namespace dictionaries — the same code works flawlessly when evaluated at module level.

## Root Cause Analysis

Python's `exec()` behaves differently depending on where it is called due to how Python resolves namespaces:

- **At module level**, `globals()` and `locals()` point to the **same** dictionary. Names bound by `exec()` enter this shared namespace, and any nested function defined within the evaluated code uses the same dictionary for global name lookup. Everything works transparently.

- **Inside a function body**, `globals()` and `locals()` are **different** dictionaries. When `exec()` is called without explicit namespace arguments, it implicitly uses the function's `locals()` as the execution namespace. Names bound by the evaluated code land in this local dictionary. However, any **nested function** defined within the evaluated code creates its own local scope and performs global name resolution against the **host module's `globals()`** — not the function-local dictionary where the names were actually stored. This namespace fragmentation causes `NameError` for names that are visibly defined in the evaluated string but invisible to nested callables.

The cognitive trap is that `exec()` appears to behave identically everywhere. The divergence between `globals()` and `locals()` inside a function is an implicit assumption violation that only surfaces when the evaluated code contains nested scopes.

## Solution Strategy

### 识别信号
- 观测到的现象: `NameError` raised at runtime for names (imports, variables, constants) that are clearly defined at the top level of a dynamically evaluated code string, but only when those names are referenced from within a nested function or class defined in the same evaluated code. The error occurs exclusively when `exec()` is called from inside a function body, not at module level.

### 解决步骤
1. **Locate all `exec()` call sites** in the codebase that are invoked inside function or method bodies rather than at module scope.
2. **Check whether explicit namespace dictionaries** (`globals` and/or `locals`) are passed to each `exec()` call.
3. **For calls lacking explicit namespaces**, create or obtain a shared dictionary to serve as the execution namespace. This can be the enclosing module's `globals()`, a purpose-built dictionary seeded with `{"__builtins__": __builtins__}`, or any single dictionary that will serve as both globals and locals.
4. **Pass the shared dictionary as the `globals` argument** to `exec()`. Either pass the same dictionary as both `globals` and `locals`, or pass only `globals` (omitting `locals` so it defaults to the same dictionary). This ensures top-level bindings and nested callable scopes share a unified namespace.
5. **Validate the fix** by writing or running a test where the evaluated code defines an import (or variable) at the top level and a nested function that references it. Confirm no `NameError` is raised.

### Why This Works

Passing an explicit globals dictionary to `exec()` forces all top-level bindings in the evaluated code into that dictionary. Crucially, any function defined within the evaluated code will use this **same** dictionary for global name resolution (per Python's scoping rules, a function's `__globals__` is set to the globals dict of the namespace in which it was defined). This eliminates the namespace fragmentation — the evaluated code's top-level scope and its nested functions' global scope become one and the same, restoring behavior identical to module-level execution.

## Boundary Cases

- **`exec()` at module level**: No fix needed — `globals()` and `locals()` are already the same dictionary, so the fragmentation never occurs.
- **Evaluated code with no nested callables**: No fix needed — all names resolve within the single implicit local scope without issue.
- **Multiple `exec()` calls sharing state**: If sequential `exec()` calls need to share bindings (e.g., one defines a variable, another reads it), they must share the same explicit namespace dictionary across calls.
- **Security-sensitive contexts**: Passing `globals()` of the host module exposes the host's namespace to the evaluated code. In sandboxed or security-sensitive scenarios, use an isolated dictionary seeded only with `__builtins__` to limit exposure.
- **`eval()` with expressions containing lambdas or comprehensions**: The same scoping issue can arise with `eval()` if the expression contains nested scopes (e.g., generator expressions referencing outer names). The same fix applies.
- **`locals()` mutation expectations**: Code that relies on `exec()` populating the function's actual `locals()` will need adjustment, since an explicit namespace redirects bindings away from the function's local scope.

## PR Examples
- django__django-13660