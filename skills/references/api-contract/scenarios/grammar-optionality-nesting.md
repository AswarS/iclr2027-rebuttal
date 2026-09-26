## Problem Description

When a format specification string (e.g., in error messages, help text, or documentation) uses bracket notation to describe optional and mandatory components of a structured input, the bracket nesting can be written in a way that describes a fundamentally different grammar than what the actual parser implements. This occurs specifically when the input has **nested optionality** — where some optional components are only valid in the presence of other optional components — and the specification author reasons about optionality from the wrong direction (outermost-in rather than innermost-out).

For example, a duration format like `[HH:[MM:]]ss[.uuuuuu]` incorrectly implies that `MM:` is optional *within* an already-optional `HH:` prefix, meaning you could provide hours without minutes. But if the actual parser requires minutes whenever hours are present (building from a mandatory `ss` core outward: `ss` → `MM:ss` → `HH:MM:ss`), the correct notation is `[HH:MM:]ss[.uuuuuu]` or `[[HH:]MM:]ss[.uuuuuu]` — where the nesting reflects the true dependency chain.

## Root Cause Analysis

The root cause is a **mental model inversion** when reasoning about optionality in layered grammars. There are two competing directions of reasoning:

1. **Outside-in (incorrect):** "Hours are optional, and if hours are present, minutes are optional within them." This produces `[HH:[MM:]]ss` — implying hours alone (without minutes) is valid.
2. **Inside-out (correct):** "Seconds are mandatory. Minutes optionally wrap seconds. Hours optionally wrap the minutes-seconds pair." This produces `[[HH:]MM:]ss` — correctly reflecting that hours require minutes.

The bracket nesting in standard grammar notation means: **the outermost brackets represent the most independently optional components, and inner brackets represent components whose presence depends on the outer component also being present.** When the dependency chain is inverted in the specification, the documented format accepts inputs the parser rejects and vice versa — a symmetry-breaking violation between the contract (error message/documentation) and the implementation (parser logic).

This is an **implicit assumption violation**: the specification author assumed a particular dependency direction without verifying it against the actual parsing code.

## Solution Strategy

### 识别信号
- 观测到的现象: Incorrect error messages or help text that describe a format the parser does not actually accept. Users following the documented format receive unexpected parse errors, or the format string in an error message is logically inconsistent with the parser's behavior.
- A format specification with bracket nesting where removing an outer optional group yields an input the parser rejects.
- Complaints or confusion about which components of a structured input are truly optional.

### 解决步骤
1. **Identify the mandatory core:** Trace the actual parsing logic to determine which component must always be present for a valid parse. This is the innermost, un-bracketed element in the correct specification.
2. **Map the dependency chain outward:** Determine which optional component can appear on its own (directly wrapping the mandatory core), and which optional component requires another optional component to also be present. Build the chain: `mandatory` → `first optional layer` → `second optional layer` → ...
3. **Construct brackets inside-out:** The mandatory component gets no brackets. The first optional layer gets brackets around itself plus the mandatory core. Each subsequent dependent layer nests inside the previous layer's brackets. For example: `ss` → `[MM:]ss` → `[[HH:]MM:]ss`.
4. **Verify by bracket removal:** Mentally remove each bracketed group one at a time. Every resulting string must be a valid input according to the parser. If removing a bracketed group produces an invalid input, the nesting is wrong.
5. **Cross-check with representative inputs:** Test the minimal valid input (mandatory only), each intermediate level (one optional layer added at a time), and the maximal input (all optional layers present) against the actual parser.

### Why This Works

Bracket notation in format specifications is a **grammar notation** where nesting encodes dependency: an inner bracket's content is only optionally present *given that* the outer bracket's content is present. By anchoring on the mandatory component and building outward following the actual parser's dependency chain, the bracket nesting faithfully mirrors the parser's grammar. The verification step (removing each bracket group independently) serves as a correctness invariant — it ensures the specification and the implementation agree on every valid input combination.

## Boundary Cases
- **Multiple independent optional components:** When optional parts do not depend on each other (e.g., an optional prefix and an optional suffix around a mandatory core), they should be in separate, non-nested bracket groups — not nested inside each other.
- **Symmetric optionality confusion:** When two components appear to be peers but actually have a dependency (e.g., minutes and hours), the dependency must be determined from the parser, not from intuition about the domain.
- **Format strings used in multiple contexts:** The same format specification may appear in error messages, documentation, and help text. All instances must be updated consistently to avoid divergent contracts.
- **Parsers with multiple valid grammars:** Some parsers accept multiple distinct formats (e.g., `HH:MM:ss` OR `MM:ss` OR `ss`). The bracket notation must unify these into a single consistent nesting, or multiple alternative formats should be listed explicitly if they cannot be cleanly nested.

## PR Examples
- **django__django-11049**: The duration field's error message described the format as `[DD] [HH:[MM:]]ss[.uuuuuu]`, implying hours could appear without minutes. The actual parser requires minutes whenever hours are present (building from mandatory seconds outward), so the correct format specification needed corrected bracket nesting to reflect the true dependency chain.