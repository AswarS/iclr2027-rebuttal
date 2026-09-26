## Problem Description

When a regex pattern is used to extract named placeholders (e.g., `{field_name}`) from user-provided template or format strings, an overly permissive capture group can match content that is not a valid placeholder. This commonly occurs when the regex uses broad character classes like `.+?` or `[^}]+` to capture text between brace delimiters, causing literal or escaped brace sequences (e.g., `{{ }}`) and arbitrary text within braces to be misidentified as placeholder names. The result is spurious validation warnings, incorrect error messages, garbled output, or silent misinterpretation of template content.

## Root Cause Analysis

Format string placeholder names follow a strict grammar — they are identifiers composed exclusively of word characters (letters, digits, underscores). When the regex used to extract these placeholders is more permissive than the grammar it is meant to represent, it captures unintended content. The fundamental principle violated is that **extraction/validation patterns must mirror the actual grammar of the construct they parse**.

The cognitive trap is an implicit assumption that all content appearing between brace delimiters must be a placeholder. The developer's mental model treats the delimiter pair `{ ... }` as sufficient for identification, overlooking the fact that:

1. Users may embed literal braces containing arbitrary text (spaces, quotes, punctuation).
2. Escaped brace sequences (`{{`, `}}`) are valid in many template languages and should not be parsed as placeholders.
3. The content between delimiters must itself conform to the expected identifier syntax to be a valid placeholder.

This is an instance of the broader **implicit assumption violation** pattern: the code assumes a constrained input space that the actual usage does not guarantee.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Spurious warnings about unrecognized template arguments or unknown field names
  - Garbled or truncated rendered output when templates contain literal braces
  - Content inside literal/escaped brace sequences (e.g., `{{ some text }}`) being misinterpreted as placeholder names
  - Validation logic rejecting valid template strings that contain non-placeholder brace content

### 解决步骤
1. **Locate the extraction regex**: Find the regex pattern responsible for extracting placeholder names from the template string. Look for patterns like `\{(.+?)\}`, `\{([^}]+)\}`, or similar constructs in validation or rendering logic.
2. **Audit the capture group**: Determine whether the character class inside the capture group (e.g., `.+?`, `[^}]+`) can match characters that are invalid in the placeholder grammar — such as spaces, quotes, punctuation, or other non-identifier characters.
3. **Restrict the capture group to the actual grammar**: Replace the overly broad character class with one that matches only valid placeholder identifiers. For Python-style format strings, use `\w+` (or `[a-zA-Z_]\w*` for stricter identifier matching) instead of `.+?` or `[^}]+`. If the grammar supports attribute access or indexing (e.g., `{obj.attr}`, `{list[0]}`), extend the pattern accordingly but no further.
4. **Verify escaped/literal braces are excluded**: Confirm that sequences like `{{`, `}}`, and `{{ arbitrary text }}` are no longer captured as placeholders. These should pass through the regex without producing matches.
5. **Add regression tests**: Create test cases with templates containing literal braces around arbitrary text (spaces, punctuation, quotes), escaped brace sequences, and mixed usage of real placeholders alongside literal braces.

### Why This Works

By constraining the regex capture group to match only characters that are valid in the placeholder grammar, the extraction logic becomes aligned with the actual syntax it is meant to parse. Content between braces that does not conform to the identifier grammar is correctly ignored rather than misidentified. This eliminates the class of false positives caused by the mismatch between the regex's permissiveness and the grammar's strictness.

## Boundary Cases
- **Escaped/doubled braces**: `{{ }}` and `{{literal text}}` must not produce placeholder matches; they represent literal brace characters in most template languages.
- **Placeholders with attribute access or indexing**: `{obj.attr}` or `{items[0]}` may be valid in some format string grammars — the regex must be extended to cover these if needed, but still reject arbitrary content.
- **Adjacent placeholders and literals**: Templates like `{name} said {{hello}}` must correctly extract only `name` as a placeholder.
- **Empty braces**: `{}` may represent positional arguments in some grammars; the regex should handle this per the specific grammar's rules.
- **Unicode identifiers**: If the target language supports unicode identifiers, `\w+` may need locale or flag adjustments to match correctly.
- **Nested braces in format specs**: `{value:{width}.{precision}}` — format specifications can contain nested braces, which require more sophisticated parsing than a simple regex.

## PR Examples
- pylint-dev__pylint-7993