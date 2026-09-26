## Problem Description

When two or more subsystems independently produce metadata about the same logical entities but adopt different canonical representations for identifiers—one stripping syntactic prefixes/decorators (e.g., `*args`, `**kwargs` → `args`, `kwargs`) while the other preserves them—a downstream merge step that joins data by identifier name will fail to reconcile entries. This results in duplicate entries in the merged output, missing metadata on some entries, or both. The duplicates differ only in the presence or absence of a syntactic marker on the identifier name, revealing that the merge logic implicitly assumed a single shared naming convention that never existed.

This pattern is a specific instance of **symmetry-breaking across pipeline stages**: each stage independently makes a reasonable normalization choice for its own purposes, but no explicit contract governs how identifiers should look when they meet at a merge boundary.

## Root Cause Analysis

The underlying principle is an **implicit assumption of identifier-form agreement** between decoupled subsystems. Each subsystem has a different concern:

- **Subsystem A** (e.g., a type-annotation processor) cares about the *semantic identity* of a parameter and strips syntactic decorators as noise.
- **Subsystem B** (e.g., a signature introspector) cares about the *syntactic role* indicated by a prefix and preserves it as meaningful metadata.

Neither subsystem is wrong in isolation. The bug emerges at the **merge boundary**, where an equality-based lookup (`dict[name]`) silently fails to find a match because `"args" != "*args"`. Because the lookup returns no match, the merge logic treats the entity as absent and either drops metadata or creates a duplicate entry. This is a classic **implicit-assumption violation**: the merge code was written under the assumption that both sources would agree on form, but that assumption was never enforced or documented.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Duplicate entries appear in merged/generated output that differ only by a syntactic prefix or decorator on the identifier name.
  - Some entries are missing expected metadata (e.g., type annotations, descriptions) that should have been merged from a second source.
  - The problem manifests only for identifiers that carry optional syntactic markers (e.g., `*`, `**`, `&`, `@`), while plain identifiers merge correctly.

### 解决步骤
1. **Trace the identifier lifecycle end-to-end.** Map the full path of the identifier from each source subsystem to the merge point. Document where each source normalizes, strips, or preserves syntactic markers. This reveals the exact point of divergence.
2. **Probe for alternate representations at the merge boundary.** Before performing an equality-based lookup, check whether a known alternate form of the identifier exists in the target data structure. If the lookup key is a bare name (e.g., `args`), also check for prefixed variants (`*args`, `**args`); if the key is prefixed, also check the stripped form.
3. **Remap the working key to the matched form.** When an alternate-form match is found, reassign the working name variable to the matched (canonical) form so that all subsequent operations—existence checks, field generation, insertion—use a single consistent representation.
4. **Capture associated values before remapping.** Store any values (annotations, descriptions, metadata) associated with the original key into a local variable before switching to the remapped key. This avoids a second lookup and prevents accidental mutation of the source dictionary.
5. **Add regression tests for both bare and decorated forms.** Create test cases that exercise the merge path with identifiers in both representations, ensuring that metadata is correctly unified regardless of which form each subsystem produces.

### Why This Works

The fix reconciles the naming gap **at the point of consumption** rather than forcing either upstream subsystem to change its canonical form. This is minimal and avoids cascading side effects through the pipeline. By explicitly bridging the two representations at the merge boundary, the solution converts an implicit assumption (both sides agree) into an explicit reconciliation step (we check and adapt). This respects each subsystem's independent design rationale while guaranteeing correct behavior at the integration seam.

## Boundary Cases

- **Identifiers with no syntactic prefix:** These already match across subsystems and must continue to work without interference from the alternate-form probing logic.
- **Multiple prefix variants for the same base name:** e.g., `*args` and `**kwargs` share the base `args`/`kwargs` but with different prefixes. The probing logic must try the correct set of prefixes for each identifier, not just a single alternate form.
- **Identifiers that legitimately differ only by prefix:** In some domains, `x` and `*x` may refer to genuinely different entities. The reconciliation logic must be scoped to contexts where the prefix is purely syntactic decoration, not semantic differentiation.
- **Empty or missing metadata on one side:** The merge must handle the case where one subsystem has an entry and the other does not, even after alternate-form probing—this is a legitimate "no metadata" case, not a bug.
- **Order-dependent merge behavior:** If the merge iterates one source and looks up in the other, the direction of iteration matters. The alternate-form check must be applied regardless of which source is the "driver" and which is the "lookup target."

## PR Examples

- **sphinx-doc__sphinx-10451**: Sphinx's autodoc and type-annotation subsystems used different canonical forms for `*args`/`**kwargs` parameter names, causing duplicate or annotation-less entries in generated documentation. The fix reconciles identifier forms at the merge point in the documentation generator.