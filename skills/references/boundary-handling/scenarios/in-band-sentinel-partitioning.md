## Problem Description

When sorting or grouping items into logical categories (e.g., "symbols" vs. "alphabetic entries" in an index), developers often prepend or append a sentinel character to sort keys to force one category before or after another. This sentinel is chosen from the same character space as the data itself (in-band). The implicit assumption is that the sentinel's code point is higher or lower than all possible values in the opposing group. This assumption breaks when the input domain is wider than anticipated — most commonly when Unicode characters beyond the ASCII range appear. The result is that items "escape" their intended group, producing duplicate group headers, split groups, or incorrect ordering in the final output.

## Root Cause Analysis

The fundamental issue is **using an in-band value as a partition discriminator within a totally-ordered but unbounded value space**. Developers mentally model the input as a narrow, familiar subset (typically ASCII or Latin-1) and select a sentinel character whose code point sits just outside that subset — e.g., `chr(127)`, `chr(255)`, or `'\xff'`. However, Unicode contains over 140,000 assigned characters with code points ranging up to `U+10FFFF`. Non-alphabetic symbols, currency signs, mathematical operators, arrows, emoji, and CJK characters have code points scattered throughout the entire space — both below *and* above the Latin alphabet range. When such characters appear in the input, the sentinel no longer reliably separates the two groups: some "symbol" items sort after the sentinel and land in the "alphabetic" group, or vice versa. This produces non-contiguous groups and duplicate headers in any downstream renderer that detects group boundaries by scanning for changes in the group key.

The deeper principle: **in-band sentinels are inherently fragile because they occupy the same value space as the data they attempt to partition.** Any growth in the input domain can invalidate the sentinel's ordering guarantee.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Duplicate group headers appear in rendered output (e.g., two separate "Symbols" sections in a generated index)
  - Items that belong to one logical group are split across two or more non-contiguous regions after sorting
  - The defect manifests only when input contains characters outside the ASCII/Latin-1 range (e.g., Unicode symbols like `Ʃ`, `€`, `→`, or CJK characters)
  - Sorting logic contains character-prepending tricks such as `key = chr(N) + original_key` to force ordering

### 解决步骤
1. **Locate the sentinel-based partitioning logic.** Search for sort-key construction that prepends or appends a special character (e.g., `chr(127)`, `'\xff'`, `'_'`) to push items into a desired position. Look for comments like "sort symbols first" or "force to end."
2. **Audit the category assignment function.** Determine how items are classified into groups (symbol vs. alphabetic, special vs. normal). Check whether the classification covers the full Unicode range, including underscore-prefixed identifiers, locale-specific characters, and non-Latin scripts.
3. **Replace the in-band sentinel with an out-of-band tuple key.** Construct a composite sort key as `(group_id: int, normalized_key: str)` where `group_id` is an explicit integer that unambiguously assigns each item to its category (e.g., `0` for symbols, `1` for alphabetic). Python's tuple comparison resolves the integer first, making it structurally impossible for any character's code point to cross the group boundary.
4. **Normalize the secondary key consistently.** Within each group, ensure the `normalized_key` uses a stable comparison basis (e.g., `unicodedata.normalize` + case folding) so that items within a group sort predictably regardless of script.
5. **Verify downstream consumers.** Confirm that renderers, formatters, or template logic that detect group transitions (by watching for changes in the group label) now see each group as a single contiguous block after sorting. Run tests with inputs spanning ASCII symbols, Latin letters, accented characters, and high-code-point Unicode symbols.

### Why This Works

A tuple-based sort key with an explicit integer partition is **order-theoretically complete**: the integer comparison fully resolves group membership before the secondary string key is ever consulted. No character — regardless of its code point — can "escape" its assigned group, because the group discriminator lives in a separate, bounded dimension (a small integer) rather than sharing the unbounded Unicode code-point space. This is the distinction between **in-band** and **out-of-band** discrimination: out-of-band discriminators are structurally immune to domain expansion.

## Boundary Cases
- **Underscore-prefixed identifiers** (e.g., `_private_var`): Must be explicitly assigned to either the symbol group or the alphabetic group; the category function should handle leading underscores as a deliberate design choice, not leave them to fall wherever their code point lands.
- **Non-Latin alphabetic characters** (e.g., Greek `Σ`, Cyrillic `Д`, CJK ideographs): These are alphabetic but have code points far above ASCII; they must be classified as alphabetic by the category function (e.g., using `unicodedata.category()` starting with `'L'`).
- **Unicode symbols with high code points** (e.g., emoji `🔧 U+1F527`, mathematical symbols `∑ U+2211`): These are non-alphabetic but have code points that interleave with or exceed alphabetic ranges — the exact scenario that breaks sentinel-based partitioning.
- **Locale-sensitive collation**: Some locales treat certain characters (e.g., `Å` in Swedish) as distinct sorting entities; the tuple approach still works because group assignment is independent of intra-group collation order.
- **Empty or whitespace-only keys**: The category function should handle degenerate inputs gracefully, assigning them to a defined group rather than relying on default character comparison.

## PR Examples
- **sphinx-doc__sphinx-7975**: Sphinx's general index used a sentinel character to sort "symbol" entries before alphabetic entries. Unicode symbols with code points above the sentinel escaped the symbol group, producing duplicate "Symbols" headers and split groups in the rendered index. The fix replaced the sentinel with a tuple-based sort key using an integer group discriminator.