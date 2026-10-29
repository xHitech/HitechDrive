# Contributing to HitechDrive

Thanks for helping make Google Drive mirroring on Linux more useful. English and Portuguese contributions are welcome.

## Start here

- Try the [offline demo](docs/demo.html), or use a small test folder and a disposable destination.
- Check existing issues before opening a new one.
- Explain the problem and expected behavior before proposing a large redesign.
- Useful first contributions include documentation fixes, clearer Portuguese copy, accessibility improvements and reproducible bug reports.

## Report a bug

Use the [bug report form](https://github.com/xHitech/HitechDrive/issues/new/choose). Include your Linux distribution, Python version, revision, steps to reproduce, expected result and actual result. For performance reports, distinguish Google transfer speed, network traffic and disk activity.

**Redact logs and screenshots before uploading.** Never attach OAuth JSON, tokens, recovery exports, account details, private file names, device serials, addresses or the contents of your private state directory. Use made-up names. Report security issues as described in [SECURITY.md](SECURITY.md).

## Work locally

Python 3.11+ and Node.js are enough for the normal checks. The application itself uses Python's standard library; it does not require Node.js or Pillow at runtime.

```bash
python -m unittest -v
node --check static/ui.js
node --check static/diagnostics.js
node --check static/theme.js
node --check static/maintenance.js
node --check tools/demo-fixture.js
node tools/verificar-demo.cjs
bash -n iniciar.sh instalar-servico.sh tools/publicar-github.sh tools/lancar-github.sh
```

Tests use temporary directories and simulated responses. Never point development tests at a real media library, raw disks or production OAuth state. Meaningful tests should cover changed behavior, especially preservation, recovery and authentication boundaries.

## Demo and media

After editing the UI, regenerate the self-contained demo:

```bash
python tools/gerar-demo.py
```

The illustrative promotional images are generated separately with Pillow, an optional developer-only package:

```bash
python tools/gerar-midia.py
```

These images are labeled as illustrations. Do not describe them as measurements or screenshots of a production account. After deliberate media edits, visually review the files and update their SHA-256 entries in `tools/verificar-publicacao.py`. The publication checker permits only those reviewed binary assets, rather than accepting arbitrary images.

## Send a pull request

Keep changes focused. Describe the problem, resulting behavior and checks you ran. Do not commit private runtime state or generated recovery files. Contributions are distributed under the project's [MIT license](LICENSE).
