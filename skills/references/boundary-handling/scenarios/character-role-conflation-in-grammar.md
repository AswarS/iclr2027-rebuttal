## Problem Description

When a validation regex or parser is tightened to exclude certain characters from an input field, characters that serve **dual syntactic roles** — acting as delimiters in one grammatical context but as legitimate content in another — get globally banned. This causes regressions where previously valid inputs are rejected with malformed-input errors after a version upgrade. The core issue is that a negated character class in a regex is positionally blind: it excludes a character everywhere in the match, even in positions where that character is structurally valid. This pattern emerges whenever a grammar has overlapping use of special characters across different productions or positional contexts.

## Root Cause Analysis

The underlying principle is **character-role conflation**: the assumption that a given character has exactly one grammatical function across all input positions. When a developer tightens a regex to prevent misparses involving a character in its delimiter role (e.g., `[` meaning "start of default value"), they introduce a global exclusion that also bans the character in its content role (e.g., `[` meaning "this sub-expression is optional"). This is an **implicit assumption violation** — the invariant that "all previously accepted inputs remain accepted" erodes silently because the developer's mental model covers only the most common input forms, not the full space of valid inputs. The regex, being a flat pattern with no positional awareness, cannot distinguish between the two roles, and the developer doesn't compensate with post-match logic.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Users report **incorrect error messages** (e.g., "malformed input") on inputs that were valid in a prior version.
  - **Regression on edge cases** after a parser or validation regex is updated.
  - The rejected inputs contain characters that are also used as structural delimiters elsewhere in the grammar.
  - The changelog or diff shows a negated character class (`[^...]`) that was expanded to exclude additional characters.

### 解决步骤
1. **Diff the validation rule**: Identify the regex or parser rule that changed, and compare the old and new character exclusion sets to pinpoint which characters were newly banned.
2. **Enumerate all syntactic roles**: For each newly excluded character, catalog every distinct role it plays across all valid input forms — not just the production the original developer was targeting. Consult documentation, historical test cases, and real-world usage to ensure full coverage.
3. **Relax the regex minimally**: Remove only the overly-broad exclusion for characters that have legitimate uses in other positions. Do not make the regex fully permissive — keep exclusions for characters that truly have no valid role in the matched region.
4. **Add post-match correction logic in code**: Handle ambiguous parses outside the regex. For example, when a character could belong to either the name component or the argument component, use heuristics such as bracket balancing, greedy/lazy boundary detection, or positional context to reassign it to the correct parsed component.
5. **Add dual-context test cases**: Write tests that exercise the ambiguous character in both its structural-delimiter role and its legitimate-content role, ensuring neither regresses.

### Why This Works

A regex negated character class is a blunt instrument — it enforces a positionally uniform exclusion. Real grammars are context-sensitive: the same character means different things depending on where it appears. By relaxing the regex to permit the character and then disambiguating in code with context-aware logic (bracket depth tracking, positional heuristics), you restore the parser's ability to handle the full input space while still rejecting genuinely malformed inputs. This separates the concern of "what characters can appear" (regex) from "what structure is valid" (code logic), which is the correct decomposition for grammars with overlapping character roles.

## Boundary Cases
- **Nested dual-role characters**: The ambiguous character appears multiple times at different nesting depths (e.g., `func([x[, y]])`) — bracket-balancing heuristics must handle arbitrary depth, not just one level.
- **Character at the boundary between two productions**: The character sits exactly at the seam where the name component ends and the argument/default-value component begins, making greedy vs. lazy matching critical.
- **Empty or minimal inputs**: Inputs where the dual-role character is the only content (e.g., a name that is just `[]`), stress-testing whether the post-match logic degrades gracefully.
- **Escaped or quoted instances**: The character appears inside a quoted string or is escaped, meaning it should be treated as literal content regardless of its usual syntactic role.
- **Multiple ambiguous characters in the same input**: More than one type of dual-role character co-occurs, requiring the disambiguation logic to handle interactions between them.

## PR Examples
- **sphinx-doc__sphinx-8506**: A validation regex for option-description parsing was tightened to exclude bracket characters, which broke inputs using brackets to denote optional sub-expressions — a legitimate and previously accepted syntactic form distinct from the delimiter role the developer was guarding against.