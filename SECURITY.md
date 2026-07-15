# Security policy

## Supported versions

LakatoTree has not published a tagged release yet. During pre-release development,
security fixes are made against the latest revision of the default branch only.
No support window or response-time guarantee is currently offered.

## Reporting a vulnerability

Do not disclose exploit details in a public issue.

Use the repository's enabled [private vulnerability-reporting
form](https://github.com/gj3447/lakatotree/security/advisories/new). If that form
is temporarily unavailable, open a minimal issue requesting a private coordination
channel without including the vulnerability, affected data, credentials, or
proof-of-concept details.

Please include privately:

- the affected revision or commit SHA;
- the component and deployment mode;
- reproduction steps or a minimal proof of concept;
- the expected and observed security boundary;
- the likely impact and any known mitigation.

Relevant boundaries include authentication and write certificates, filesystem
and result-path confinement, provenance or receipt forgery, unsafe deserialization,
secret exposure, dependency or release integrity, and unauthorized database
mutation.

The maintainer will validate the report, coordinate a fix where possible, and
credit the reporter unless anonymity is requested. Public disclosure should wait
until a fix or practical mitigation is available.

## Operational safety

Never include API tokens, database credentials, private datasets, or full process
environments in reports. Redact logs to the minimum evidence needed to reproduce
the issue.
