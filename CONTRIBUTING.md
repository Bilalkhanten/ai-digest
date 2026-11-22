# Contributing

Thanks for your interest. A few things to know first.

## Pull requests

This repository enforces a **sole-author policy** in CI (`scripts/check_authors.py`): commits must
come from the identities listed in `.github/allowed-authors.txt`. That means pull requests from
other accounts will fail CI, so I'm not able to merge them directly.

What helps instead:

- **Open an issue** describing a bug, an idea, or a project the pipeline should handle better. Include
  the digest page or run link if relevant.
- **Fork it** and adapt it freely. The "Run your own copy" section of the README explains the setup.
- **Report security problems privately**, see [SECURITY.md](SECURITY.md).

## Working on a fork

```bash
python3 -m unittest discover -s tests          # offline; never contacts GitHub
pip install ruff==0.17.5 mypy==2.4.1 coverage==7.17.2
ruff check . && mypy                            # lint and types
cd copilot && npm ci && npm test                # the TypeScript incident copilot
```

CI additionally runs actionlint, shellcheck, a coverage floor, and a real-cluster end-to-end test
for the copilot, so those are worth running before you push a change.

## Project values

Read-only wherever possible, no hidden side effects, untrusted text is always sanitised, and every
change comes with tests.
