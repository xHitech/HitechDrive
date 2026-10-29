# Security

HitechDrive is experimental software that handles private Google Drive metadata and local files. The latest `main` revision is the only actively maintained version; there is no formal security support window.

## Reporting a vulnerability

If GitHub shows **Security → Report a vulnerability** for this repository, use that private reporting channel. Do not put credentials, exploitable details or private files in a public issue.

If private reporting is unavailable, open an issue containing only a request for a private reporting channel. Wait for a maintainer to arrange it before sharing sensitive details. No response-time guarantee is offered.

Never share OAuth credentials or tokens, recovery backups, raw state directories, private file paths, IP addresses or disk serial numbers. Use synthetic examples when possible.

## Operating boundaries

The dashboard is designed for loopback access, optionally through SSH. Keep Google access read-only and use a dedicated destination. Synchronization and RAID do not replace an independent backup. See the README for preservation and recovery limitations.
