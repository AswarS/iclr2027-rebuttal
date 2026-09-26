## Problem Description

When rendering structured text output that uses delimiter characters (parentheses, brackets, braces) as vertically stacked Unicode character sequences, searching for a delimiter's boundary position using a forward scan (`find`) incorrectly locates an interior occurrence rather than the true outer edge. This occurs because tall expressions (fractions, integrals, nested structures) cause the rendering engine to repeat extension characters vertically, producing multiple instances of the same delimiter character across different lines. A label or suffix intended to appear outside the delimiter is instead inserted at an interior position, causing visual corruption or incorrect output.

## Root Cause Analysis

The fundamental issue is an **implicit assumption that each logical delimiter maps to exactly one rendered character instance**. In multi-line pretty-printing systems, a single closing parenthesis or bracket is rendered as a vertical stack: an upper hook, zero or more extension segments, and a lower hook. The extension character is repeated proportionally to the height of the enclosed content. When code uses a forward search (`find`) to locate "the" delimiter character, it finds the **first** (topmost) occurrence — which sits in the visual middle of tall expressions. The **last** (bottommost) occurrence is the true outer boundary where suffixes, labels, or annotations should be placed.

This is a boundary-condition neglect pattern: the code works correctly for single-line or short expressions (where there is only one occurrence of the delimiter character), but fails for taller expressions where the delimiter spans multiple lines. The developer's mental model conflated the logical delimiter with a single character, not accounting for the one-to-many relationship between logical structure and rendered representation.

## Solution Strategy

### 识别信号
- 观测到的现象: Labels, suffixes, or annotations appear visually inside or overlapping with delimiter characters rather than outside them; Unicode rendering corruption in multi-line pretty-printed output; output is correct for simple/short expressions but breaks for tall/complex ones (e.g., fractions, integrals, deeply nested structures).

### 解决步骤
1. **Audit all delimiter search operations**: Locate every instance where the code searches for a delimiter character in rendered multi-line strings. Determine whether the search is intended to find the outermost boundary (first vs. last occurrence).
2. **Replace forward search with reverse search**: For closing delimiters where the insertion point should be at the outer edge, change `find` to `rfind` (or equivalent reverse/end-anchored search) to locate the last occurrence of the delimiter character, which corresponds to the true boundary.
3. **Validate insertion context**: After locating the candidate position, verify it is genuinely at the boundary by checking adjacent characters — e.g., confirm a newline follows, or that the character is at the expected vertical position (baseline) relative to the expression.
4. **Remove incorrect fallback paths**: If the code contains fallback logic that inserts at alternative delimiter positions (e.g., upper hook when the extension search fails), remove or simplify these paths if they can never produce correct results.
5. **Test across expression heights**: Validate with single-line expressions (height 1), medium expressions (height 3, e.g., simple fractions), and tall expressions (height 7+, e.g., integrals with complex bounds) to confirm the label consistently appears outside the delimiter at every height.

### Why This Works

The bottom of a vertically-rendered closing delimiter is always the **last** occurrence of the delimiter/extension character in the string representation of that line group. This invariant holds regardless of expression height because extension characters are appended downward as the content grows taller. By searching from the end, the code correctly identifies the outer boundary in all cases — collapsing to the same result as forward search when only one occurrence exists (short expressions), while correctly skipping interior occurrences for tall expressions.

## Boundary Cases

- **Single-line expressions**: Only one delimiter character exists; forward and reverse search produce identical results. Ensure the fix does not regress this case.
- **Expressions at the exact threshold height** where the delimiter transitions from a single character to a multi-character stack (typically height 2 or 3 depending on the rendering system).
- **Multiple nested delimiters of different heights**: e.g., `(a + (b/c))` where inner and outer parentheses have different heights — the reverse search must find the correct delimiter, not a character belonging to a different nesting level.
- **Delimiters appearing in content**: If the delimiter character can appear as literal content (not as a structural boundary), the search must distinguish structural delimiters from content characters, potentially by restricting the search to known column positions.
- **Empty or minimal content inside delimiters**: Height-1 delimiters where extension characters are absent entirely.

## PR Examples

- sympy__sympy-23191