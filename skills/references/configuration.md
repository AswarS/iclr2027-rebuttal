---
name: configuration
description: Bugs where configuration settings are missing, silently ignored, inconsistently propagated, or produce divergent behavior across code paths.
---

## Overview

Configuration bugs arise when the system's configurable surface fails to deliver uniform, predictable behavior — either because defaults are absent or environment-dependent, because settings are silently ignored in certain contexts, or because configuration is not propagated symmetrically across all code paths that need it.

## Patterns

### Divergent Defaults Across Convergent Paths
- **When**: Multiple internal code paths produce the same kind of output artifact, but each path inherits different default properties (e.g., permissions, encoding) from its underlying mechanism, and no explicit default is set in configuration.
- **Do**: Audit all paths that converge to the same artifact type and set an explicit, deterministic default in the configuration layer rather than deferring to the environment or each subsystem's internal policy.
- **Why**: Different libraries and subsystems override environment defaults independently (e.g., temp-file modules enforce restrictive permissions for security), so "defer to the OS" silently produces inconsistent results depending on which internal path is taken.

### Silently Ignored Configuration
- **When**: A user explicitly provides a configuration value that has no effect due to another parameter, an implicit mode, or a context that makes the setting a no-op, and the system gives no feedback.
- **Do**: Add validation that detects when an explicitly provided setting will have no effect in the current context and emit a warning (not a hard error) through the existing checks framework, co-located with any other "ignored options" validation.
- **Why**: Users configure parameters independently and expect each to take effect; silent no-ops violate least-astonishment and waste debugging time, but a warning (rather than error) avoids breaking existing deployments with benign misconfigurations.

### Incomplete Configuration Propagation
- **When**: A configuration option correctly transforms behavior in one processing path, but a parallel path that handles the same kind of input omits the configuration parameter, falling back to a default or no-op.
- **Do**: Search for every call site of the underlying transformation function and verify the configuration dictionary or parameters are passed uniformly; look specifically for calls using default arguments or omitting optional parameters, and add test coverage for each entity category.
- **Why**: Optional function parameters that default to empty or null silently skip the transformation when callers forget to pass the configuration — propagation is never automatic across sibling paths.

### Asymmetric Sibling Path Behavior
- **When**: Logically equivalent processing paths (e.g., primary vs. auxiliary section handlers) should obey the same configuration flag, but one path hardcodes a single mode while the other respects the flag.
- **Do**: Replicate the full conditional branching logic from the canonical path into every sibling path — including all sub-options and advanced features — reusing the same configuration setting rather than introducing a new one.
- **Why**: Developers treat secondary variants as less important and implement simplified unconditional versions, but users perceive sibling paths as the same category and expect symmetric behavior.

### Ambiguous Default Identifiers
- **When**: A default format template uses short, unqualified identifiers (e.g., base filename, simple label) that collide frequently in large-scale or multi-package environments, making output entries untraceable.
- **Do**: Replace short identifiers with fully-qualified, namespace-aware identifiers in the default template; lead with the most filterable field and use compact delimiters instead of fixed-width padding on variable-length fields.
- **Why**: Generic short names have high collision rates across dependencies; the original default assumes a small-world, single-package context that doesn't hold at scale.

### Overlapping Handler Domain Preemption
- **When**: Multiple configuration-driven handlers have overlapping scopes, and a more general handler silently preempts a more specific one due to registration order or match priority.
- **Do**: Ensure handler selection respects specificity or provides explicit priority controls, and warn when a registered handler can never activate.
- **Why**: Without specificity-aware dispatch, broader handlers shadow narrower ones, making targeted configuration ineffective.

### Lazy Resolution of Environment-Dependent Config
- **When**: A configuration value depends on runtime environment state (e.g., working directory, locale, available resources) but is resolved eagerly at import or initialization time, before the environment is fully set up.
- **Do**: Defer resolution of environment-dependent configuration to first use, or re-resolve when the relevant environment state changes.
- **Why**: Eager resolution captures a stale or incomplete environment snapshot, causing the resolved value to diverge from the user's expectation at actual usage time.

## Scenarios
- [lazy-resolution-of-environment-dependent-config](./scenarios/lazy-resolution-of-environment-dependent-config.md)
- [overlapping-handler-domain-preemption](./scenarios/overlapping-handler-domain-preemption.md)
- [general-listing-must-honor-same-filters-as-specialized-listi](./scenarios/general-listing-must-honor-same-filters-as-specialized-listi.md)
- [divergent-defaults-across-convergent-paths](./scenarios/divergent-defaults-across-convergent-paths.md)
- [silently-ignored-configuration](./scenarios/silently-ignored-configuration.md)
- [incomplete-configuration-propagation](./scenarios/incomplete-configuration-propagation.md)
- [asymmetric-sibling-path-behavior](./scenarios/asymmetric-sibling-path-behavior.md)
- [ambiguous-default-identifiers](./scenarios/ambiguous-default-identifiers.md)