# HitechDrive v0.1.0-alpha.1

First public preview: a visual, one-way Google Drive mirror for Linux, built with Python's standard library and vanilla JavaScript.

- Local dashboard with light/dark themes, collection progress and per-file transfers.
- 1–8 concurrent downloads, resumable binary transfers and a shared bandwidth limit.
- Incremental Drive changes and ID-based local relocation for unchanged content.
- Disk/network diagnostics, actionable alerts and explicit trash cleanup.
- Recovery exports, an on-volume checkpoint, verified file adoption and optional checksum audits.
- English introduction, Portuguese operating guide, offline demo, contribution templates and MIT license.

## Getting started

Read the repository README. A mounted volume with a UUID and personal Google Desktop OAuth credentials are required for real synchronization. No Docker or rclone is required. You can explore `docs/demo.html` without Google credentials.

## Preview limitations

This is experimental software, not an official Google client. The app UI is currently in Portuguese. Synchronization is one-way: local edits are not uploaded. Native Google files are exported; shared drives, comments, permissions and version history are not fully replicated. Keep an independent backup.

The promotional images use fictional data and are illustrative, not performance benchmarks. Checks use simulated responses and temporary directories; real account and network behavior depends on your environment.
