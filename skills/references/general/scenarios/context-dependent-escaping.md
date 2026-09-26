## Problem Description

**Context-Dependent Escaping** is a problem pattern where a blanket escaping rule is applied to special characters in a domain-specific markup language (e.g., LaTeX, HTML, XML) without accounting for the fact that the same character carries different meanings in different syntactic contexts within that language. The result is corrupted or broken output: raw markup artifacts appear in rendered content, or valid structural tokens are inadvertently transformed into nonsensical or semantically different commands.

For example, in LaTeX, the `[` character may need escaping in free-flowing text but serves as a required delimiter in command arguments (e.g., `\left[`). Escaping it universally produces `\[`, which LaTeX interprets not as a literal bracket but as a display-math-mode delimiter — a completely different construct with unrelated semantics.

## Root Cause Analysis

Markup languages are not flat text formats; they define **multiple syntactic contexts** (command arguments, delimiter positions, free-flowing text, special mode triggers, etc.) where the same character plays different roles. The root cause of this pattern is **context-blind escaping**: developers internalize a list of "special characters" for a language and apply a global escape-everywhere policy, treating the language as if it has a single, uniform grammar.

This is an **implicit assumption violation** — the code assumes that escaping is a context-free transformation, when in reality the markup language's grammar is context-sensitive. The assumption is reinforced by the fact that blanket escaping *appears* correct at a glance (every special character is "handled"), making the bug subtle and easy to miss during code review. The corruption only surfaces when the escaped output is actually rendered by the target system, which interprets the escaped sequence according to its positional grammar rules.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Rendered output displays raw markup artifacts (e.g., broken LaTeX formulas, visible HTML tags, malformed XML)
  - Encoding corruption in serialized output — characters are double-escaped or transformed into unintended command sequences
  - Output "looks correct" in source form but breaks when processed by the target rendering engine
  - A global escaping function or regex is applied uniformly across all generated output strings
  - The bug manifests only for specific content that happens to include characters with dual roles (e.g., brackets, ampersands, backslashes)

### 解决步骤
1. **Map the syntactic contexts**: Enumerate all distinct syntactic positions in the target markup language where the problematic character can appear — command arguments, delimiters, free text, mode switches, verbatim regions, etc.
2. **Consult the language specification per context**: For each context, determine whether the character is interpreted as a literal, a structural token, or a mode trigger. Document the expected behavior in each position.
3. **Check for semantic collisions**: Verify that the escaped form of the character does not coincidentally produce a valid but semantically different command in the target language (e.g., `\[` in LaTeX being display-math mode, not an escaped bracket).
4. **Replace blanket escaping with context-aware escaping**: Refactor the escaping logic so that it receives or infers the current syntactic context and applies the appropriate transformation — escaping only where the character would genuinely be misinterpreted, and leaving it untouched where it serves a required structural role.
5. **Validate in the target rendering environment**: Test the generated markup end-to-end by feeding it into the actual renderer (LaTeX compiler, browser, XML parser) and confirming that the output is visually and structurally correct across representative inputs, including edge cases with mixed contexts.

### Why This Works

Escaping is fundamentally a **context-dependent** operation. By anchoring the escaping decision to the specific syntactic position rather than to a global character blacklist, the solution respects the markup language's actual grammar. This eliminates the class of bugs where a valid structural token is destroyed by unnecessary escaping, while still protecting against misinterpretation in contexts where the character truly is ambiguous. The key insight is that **the unit of reasoning for escaping is the syntactic context, not the character itself**.

## Boundary Cases
- **Nested contexts**: A character may appear inside a nested construct (e.g., a command argument within a math environment within a text block) where each nesting level imposes different escaping rules. The escaping logic must track context depth.
- **Verbatim or raw regions**: Some markup languages provide verbatim modes where no escaping should be applied at all. Applying escaping inside these regions corrupts content that was explicitly marked as literal.
- **User-supplied content mixed with generated markup**: When literal user input is interpolated into generated structural markup, the boundary between "content that needs escaping" and "structure that must not be escaped" must be precisely maintained.
- **Characters that are special in multiple overlapping ways**: For instance, `&` in HTML is both an entity introducer and a valid character in URLs within `href` attributes — the correct handling depends on whether the parser is in attribute-value context or body-text context.
- **Escaping that produces valid but wrong commands**: The most insidious variant — the output parses without errors but renders incorrectly because the escaped form is a real command with different semantics (e.g., LaTeX `\[` vs. literal `[`).

## PR Examples
- **sympy__sympy-13971**: LaTeX printer applied blanket escaping to bracket characters, turning valid delimiter arguments (e.g., `\left[`) into display-math-mode switches (`\left\[`), corrupting rendered mathematical output.