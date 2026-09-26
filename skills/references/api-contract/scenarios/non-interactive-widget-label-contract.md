## Problem Description

When a base class or interface defines a contract for interactive elements (e.g., form widgets that produce labelable, focusable HTML controls), a display-only or non-interactive subclass inherits behavior that assumes interactivity. This results in the rendering system generating association attributes (such as `<label for="...">`) that reference elements which don't exist in the rendered output, producing semantically invalid markup with dangling references.

This pattern emerges in component/widget hierarchies where the base abstraction implicitly equates "component" with "interactive control." When a purely presentational variant is introduced, it silently inherits methods that return identifiers for non-existent interactive targets, and the rendering pipeline dutifully emits association markup based on those identifiers.

## Root Cause Analysis

The underlying issue is an **implicit assumption baked into the base class contract**: every widget/component in the hierarchy will produce an interactive, targetable element in its rendered output. This assumption is never explicitly enforced or documented — it's simply the default behavior inherited by all subclasses.

When a developer creates a display-only variant (e.g., a read-only text display widget instead of an `<input>`), they focus on overriding the rendering method to produce static content but **fail to audit all inherited methods that depend on the interactivity assumption**. The method responsible for returning an association identifier (like an `id_for_label`) continues to return a valid-looking ID, causing the label rendering system to emit a `for="some_id"` attribute pointing to nothing.

The cognitive trap is that the base class contract is implicit rather than enforced. There is no abstract method or type-system check that forces the subclass author to consider whether the association identifier is still meaningful. The framework often already supports a sentinel value (e.g., `None` or empty string) to signal "no association needed," but the display-only variant never opts into it because the developer doesn't realize the opt-out is necessary.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - Rendered HTML contains `<label for="some_id">` but no element with `id="some_id"` exists in the output
  - Accessibility validators or HTML linters report dangling `for` attribute references
  - A non-interactive or display-only widget/component inherits from an interactive base class without overriding the identifier method
  - The rendered output is semantically invalid despite appearing visually correct

### 解决步骤
1. **Identify the association method in the base class** — Locate the method responsible for providing the identifier used for label-to-element linkage (e.g., `id_for_label` in Django's widget hierarchy). Understand what return values the rendering pipeline expects and how it handles sentinel values like `None`.
2. **Verify the framework's opt-out mechanism** — Check whether the rendering layer already supports a sentinel return value (such as `None`, empty string, or a specific constant) that signals "do not emit an association attribute." In most mature frameworks, this mechanism already exists but is underutilized.
3. **Override the method in the display-only variant** — In the non-interactive subclass, override the association identifier method to return the sentinel value, explicitly signaling that no targetable element will be present in the rendered output.
4. **Confirm the rendering pipeline handles the sentinel correctly** — Trace the rendering code to verify that when the sentinel value is returned, the association attribute (e.g., `for="..."`) is omitted entirely from the label element rather than emitting an empty or malformed attribute.
5. **Add a regression test** — Write a test that renders the display-only variant within its full label context and asserts that the output does not contain a dangling association attribute referencing a non-existent element.

### Why This Works

The fix leverages the framework's existing opt-out mechanism rather than modifying the rendering pipeline or the base class. By overriding a single method to return a sentinel value, the display-only variant correctly communicates its non-interactive nature to the rendering system. This is the idiomatic approach because it respects the existing contract — the base class already anticipated that some components might not need label association; the display-only variant simply needed to declare itself as one of those cases.

The deeper principle: **any time a subclass changes the fundamental nature of what is rendered (interactive → static), all inherited methods that depend on the original nature must be reviewed and potentially overridden.** The rendering contract is bidirectional — the component tells the renderer what it is, and the renderer acts accordingly.

## Boundary Cases
- **Conditionally interactive widgets** — A component that is sometimes interactive and sometimes display-only (e.g., based on permissions or state) must dynamically return either a valid ID or the sentinel value, not just statically override the method.
- **Nested or composite widgets** — A container widget that delegates to sub-widgets may need to aggregate or suppress association identifiers depending on which sub-widgets are interactive.
- **Custom rendering pipelines** — If the rendering layer does not properly handle the sentinel value (e.g., emits `for=""` instead of omitting the attribute), the rendering code itself must also be patched.
- **Multiple label association methods** — Some frameworks have more than one method involved in label association (e.g., `id_for_label` vs. `attrs['id']`); all relevant methods must be audited.
- **Accessibility implications beyond labels** — Dangling `aria-labelledby`, `aria-describedby`, or `aria-controls` attributes follow the same pattern and require the same treatment.

## PR Examples
- django__django-14411