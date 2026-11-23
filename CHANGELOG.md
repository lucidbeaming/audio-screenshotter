# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- MIT license (#2)

### Fixed
- `analyze` starts on Windows: the recorder (which needs Unix-only `termios`) is imported only by `record`/`run` (#6)

### Changed
- `.gitignore` aligned with the portfolio's common block: logs, Windows thumbnails, Sublime workspaces, shared `.vscode/extensions.json` (#4)
