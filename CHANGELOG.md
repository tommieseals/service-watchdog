# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-06-11

### Added

- Environment variable interpolation in the config loader: `${VAR}`
  placeholders in any string value (including nested values such as notifier
  headers, service `env` maps, and address lists) are now resolved from the
  environment at load time. A reference to an unset variable fails with an
  error naming the variable. The sample config from `service-watchdog init`
  and the README already used this syntax; previously the placeholders were
  passed through literally.
- Unit tests for the watchdog core: failure-threshold counting, restart
  scheduling and alert deduplication, restart-window flap protection, and
  state persistence round-trips.
- Tests for env-var interpolation (present, missing, and nested cases).

### Changed

- CI now also enforces `black --check` and `mypy` (both were already listed
  in the Contributing section).
- Type annotations tightened in `monitor.py` and `notifiers.py` to pass
  `mypy`; no behavior change. `types-PyYAML` and `types-psutil` added to the
  dev extra.

### Removed

- The undocumented `watchdog-ctl` console-script alias. Use
  `service-watchdog`.

## [1.0.1] - 2026-06-11

Maintenance release. No functional changes to the watchdog itself.

### Fixed

- `test_load_from_yaml` failed on Windows because the temp config file was
  deleted while the `NamedTemporaryFile` handle was still open; rewritten with
  pytest's `tmp_path` fixture. The full suite now passes on Windows.
- CI now actually gates on results: the package is installed with
  `pip install -e ".[dev]"`, and the `--exit-zero` / `|| true` escape hatches
  were removed from the lint and test steps.
- All ruff findings fixed (unused imports, `Optional[X]` -> `X | None`,
  import sorting, line lengths).
- LICENSE copyright year corrected to 2026.

### Changed

- Minimum supported Python is now 3.10; CI tests 3.10/3.11/3.12 on
  ubuntu-latest and windows-latest. `requires-python`, classifiers, and tool
  configs updated to match.
- README: removed the PyPI install instructions (the package is not on PyPI;
  install from GitHub instead), replaced the feature-list-only intro with a
  real captured `status` output, added a "Running on Windows" section, and
  toned down the marketing language.
- `requirements.txt` trimmed to the dependencies the code actually imports
  (`pyyaml`, `requests`, `psutil`, `click`); `rich` and `python-dotenv` were
  declared but never used.
- Removed the placeholder author email from `pyproject.toml`.

## [1.0.0] - 2026-02-19

Initial release: process/port/PID-file/HTTP health checks, Telegram/Slack/
email/webhook notifiers, restart logic with flap protection, systemd and
launchd unit files.
