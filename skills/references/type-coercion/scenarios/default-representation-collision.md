## Problem Description

When a code generation or serialization system translates domain-specific expressions into target-language source code, it typically relies on a registry of explicit "printer" methods—one per expression type. If a domain object lacks a dedicated printer method, the system falls back to a default string representation (e.g., `str()` or `__repr__`). When that default representation happens to collide with a valid token in the target language's namespace—a built-in constant, a library symbol, or an injected global—the generated code is syntactically valid but semantically wrong. The result is **silent data corruption**: the program runs without errors but produces incorrect numerical results. This pattern is especially insidious because standard unit tests that only inspect the generated *string* will pass; only end-to-end execution tests that compare *computed values* against expected values will catch the defect.

## Root Cause Analysis

The fundamental issue is an **incomplete mapping** between the set of all possible input domain constructs and the set of valid target-language translations. Code generation systems are designed around an extensible visitor/printer pattern, but they implicitly assume that any construct without an explicit handler will either (a) never appear in practice, or (b) produce obviously invalid code that triggers a syntax error downstream. Neither assumption holds in general.

Short, common default names (single letters, common mathematical abbreviations like `I`, `S`, `N`, `E`) have a **high collision probability** with symbols that already exist in the target namespace—Python's `1j` imaginary literal aliased as `I`, NumPy's `e` or `pi`, SymPy's `S` singleton, etc. Because the fallback representation is a valid identifier in the target language, no syntax error is raised, and the semantic mismatch propagates silently through all downstream computations.

The deeper architectural principle violated is the **totality requirement** for translation functions: a code generator must either produce a correct translation for every possible input, or explicitly refuse (raise an error) when it encounters an untranslatable construct. Allowing silent fallthrough to a default representation violates this contract.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Silent wrong output**: generated code executes without errors but produces numerically incorrect results (e.g., an identity matrix operation returns complex-number-scaled results instead)
  - **String-level tests pass but numerical tests fail**: the generated code *looks* plausible on inspection
  - **Intermittent correctness**: the bug only manifests when a specific domain construct (e.g., `Identity`, `ZeroMatrix`) appears in the expression being translated, making it appear sporadic
  - **Target namespace contains common short symbols**: the code generation target imports libraries or defines globals with names like `I`, `S`, `N`, `E`, `O`, `pi`, `nan`, `inf`

### 解决步骤
1. **Enumerate all domain expression types** that can appear as inputs to the code generator. Cross-reference this list against the set of expression types that have explicit printer/handler methods. Identify every type that lacks a dedicated handler and would fall through to the default representation.
2. **For each unhandled type, determine the fallback string** it would produce (typically via `str()` or the object's name attribute). Check whether that string is a valid, already-bound symbol in the target language's execution namespace (built-ins, standard library imports, injected globals, or common convention names).
3. **Add explicit translation methods** for every construct that has a meaningful target-language equivalent. For example, map an identity matrix to the appropriate library call (`numpy.eye(n)`), a zero matrix to `numpy.zeros((m, n))`, etc.
4. **For constructs that cannot be faithfully translated** (e.g., they require symbolic dimensions not available at code-generation time), raise an explicit `NotImplementedError` or equivalent, with a clear message identifying the untranslatable construct. Never allow silent fallthrough.
5. **Add end-to-end regression tests** that execute the generated code with concrete numerical inputs and compare computed results against independently verified expected values. String-comparison tests are necessary but not sufficient—they cannot detect namespace collisions.
6. **Consider a defensive namespace audit**: at code-generation time, optionally check whether any emitted identifier collides with the target namespace's known symbols, and warn or error if so.

### Why This Works

By enforcing a **total mapping** from input constructs to either correct translations or explicit errors, the solution eliminates the category of bugs where a default representation silently collides with a target-namespace symbol. The principle is straightforward: a code generator is a compiler, and compilers must either produce correct output or reject the input—they must never silently produce wrong output. Fixing at the printer/translation layer addresses the root cause (missing translation rule) rather than attempting to sanitize the target namespace, which would be fragile and incomplete.

## Boundary Cases
- **Parameterized constructs**: Some domain objects (e.g., `Identity(n)`) carry symbolic parameters. The translation must correctly emit code that computes the right shape/value at runtime, not just a static token.
- **User-defined symbols with colliding names**: Even with complete printer coverage, a user might define a SymPy `Symbol('I')` or `Symbol('pi')`. The code generator must either rename/mangle such symbols or raise an error when they collide with target-namespace tokens.
- **Nested expressions containing unhandled types**: A well-handled outer expression (e.g., `MatMul`) may contain an unhandled inner operand (e.g., `ZeroMatrix`). The printer must recurse correctly and not assume inner operands are always handled.
- **Multiple target languages**: A construct may have a correct translation for one target (e.g., NumPy) but not another (e.g., C, Fortran, Julia). Each code generation backend must independently maintain a complete mapping.
- **Version-dependent namespaces**: Target library updates may introduce new global symbols (e.g., a new NumPy constant), creating collisions that didn't exist in earlier versions. Periodic audits of the target namespace are advisable.

## PR Examples
- sympy__sympy-17022