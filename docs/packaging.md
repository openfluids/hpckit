# Packaging notes

`jz_pilot` follows the current PyPA baseline for a small pure-Python CLI:

- package code lives under `src/jz_pilot/`;
- metadata is centralized in `pyproject.toml`;
- the public command is exposed through `[project.scripts]` as `jzp`;
- `python -m jz_pilot` is supported via `src/jz_pilot/__main__.py`;
- maintainer-only tooling uses `[dependency-groups]` instead of runtime extras;
- repository metadata includes license, classifiers, and project URLs.

The package is intended for `pipx install`/editable local use rather than as a hidden myproject subpackage. Runtime behavior still depends on the user's SSH config for Jean Zay and on Slurm/uv/git availability on the remote host.
