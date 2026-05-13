---
name: verify
description: Spawn the hardware-verifier agent for a named package's most recent PR.
invocation: /verify <pkg>
---

# /verify \<pkg\>

Spawn the `hardware-verifier` agent for the named package.

## Before spawning

1. Find the package's most recent PR:
   ```
   gh pr list --search "<pkg>" --state open
   gh pr list --search "<pkg>" --state closed --limit 5
   ```
2. Read the package spec at `.astroray_plan/packages/<pkg>*.md` to extract:
   - The most recent binding introduced (for the smoke-check step)
   - The acceptance gate list

3. Pass to hardware-verifier:
   - PR number
   - Package spec path
   - The most recent binding name (for Step 2 of the verifier's workflow)

## Reactive mode

If a PR has the `needs-verifier` label, `/verify` can also be triggered
reactively. In that case, extract the package name from the PR title.
