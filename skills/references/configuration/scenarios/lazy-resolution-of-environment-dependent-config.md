## Problem Description

Configuration values representing resource locators (URLs, file paths, asset base paths) are defined statically at application startup, but the actual deployment context—such as a sub-path prefix imposed by a reverse proxy or WSGI container—is only known at runtime and may vary per-request or per-deployment. When these configuration values are eagerly resolved at initialization time, they become stale or incorrect in environments where the deployment prefix is dynamic, leading to broken asset references, incorrect URL generation, and inconsistent behavior across subsystems that consume these settings.

## Root Cause Analysis

The fundamental issue is an **implicit assumption that deployment topology is a static, compile-time constant** that can be baked into configuration values during initialization. In reality, deployment context (sub-path prefixes, reverse proxy paths) is a runtime concern that may not be known when settings are authored or when the application module is first loaded. Because resource locator settings are consumed by many independent subsystems (template rendering, storage backends, URL generators, API responses), eagerly resolving them at startup creates a single point of failure: if the prefix changes or isn't yet available, every consumer silently receives the wrong value. The cognitive trap is treating environment-dependent configuration as if it were environment-independent.

## Solution Strategy

### 识别信号
- 观测到的现象:
  - **Wrong output**: Generated URLs or asset paths are missing the expected deployment sub-path prefix, resulting in 404s or broken references
  - **Inconsistent state**: The same configuration value produces correct results in one deployment topology but incorrect results in another (e.g., works at root `/` but breaks behind a reverse proxy at `/app/`)
  - Scattered, incomplete fixes across multiple consumption sites that each try to prepend the prefix independently

### 解决步骤
1. **Audit all configuration values that represent resource locators** — identify settings for asset base paths, media URLs, static URLs, and similar values that could be affected by a deployment-time path prefix.
2. **Classify values as absolute vs. relative** — use URL validation (presence of a scheme like `http://`) and leading separator checks (`/`) to distinguish fully-qualified or already-absolute values from bare relative paths that need prefixing.
3. **Make the settings layer dynamic via lazy/computed properties** — instead of modifying every consumption site, expose affected configuration values as computed properties that lazily prepend the runtime prefix on each access. This centralizes the logic in one place.
4. **Retrieve the deployment prefix from the runtime environment at access time** — read the prefix (e.g., from `SCRIPT_NAME`, a WSGI environ variable, or equivalent runtime source) at the moment the setting is accessed, not at module import or initialization time.
5. **Preserve backward compatibility for absolute values** — if a value is already a full URL (e.g., pointing to a CDN) or an absolute path starting with `/`, pass it through unchanged to avoid double-prefixing.

### Why This Works

Centralizing the prefix logic at the configuration/settings layer ensures that **all consumers automatically receive the correct, deployment-aware value** without requiring scattered changes across template tags, storage backends, URL generators, and other subsystems. Lazy resolution at access time rather than eager resolution at load time accommodates environments where the sub-path is set per-request or configured after application initialization. The absolute-vs-relative distinction provides an explicit escape hatch: users who have already accounted for deployment context (by specifying a full URL or absolute path) are not interfered with.

## Boundary Cases
- **Fully-qualified URLs (e.g., CDN references like `https://cdn.example.com/static/`)** must not be prefixed — the scheme detection must reliably identify these and pass them through unchanged.
- **Absolute paths already starting with `/`** should not receive an additional prefix, as the user has explicitly anchored the path.
- **Empty or unset deployment prefix** — the lazy resolution must gracefully handle the case where no prefix is configured, defaulting to no-op behavior equivalent to the pre-fix state.
- **Trailing/leading slash normalization** — when prepending a prefix like `/app` to a relative path like `static/`, the result must be correctly joined (e.g., `/app/static/`) without double slashes or missing separators.
- **Per-request variation** — if the prefix can differ between requests (e.g., multi-tenant routing), the lazy property must not cache a stale value from a previous request.
- **Settings accessed during module import** — some subsystems may read configuration at import time before the runtime environment is fully established; lazy resolution must handle or document this edge case.

## PR Examples
- django__django-11564