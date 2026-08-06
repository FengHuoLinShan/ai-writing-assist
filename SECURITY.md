# Security Policy

## Supported versions

Security fixes are provided for the current `main` branch and the commit
currently deployed by the project operator. Older commits, forks, and modified
deployments are not supported unless the maintainers explicitly say otherwise.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open
a public issue or discussion for a suspected vulnerability.

Include the affected commit, impact, prerequisites, and the smallest safe
reproduction you can provide. Never include real user data, manuscript
content, passwords, verification codes, access tokens, or LLM API keys. Use
synthetic test data and redact request and response examples.

The maintainers aim to acknowledge a report within three business days and
provide an initial status within seven business days. Resolution and disclosure
timing depend on severity, exploitability, and deployment coordination. Public
disclosure should be coordinated through the private report after a fix or
mitigation is available.

## Scope

Reports about authentication, account or `novel_id` isolation, secret handling,
unsafe content rendering, fixed-SHA deployment, backups, and production
configuration are in scope. General support requests, model output quality,
and vulnerabilities that require an already-compromised operator account
without crossing another security boundary are out of scope.
