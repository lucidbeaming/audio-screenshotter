# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-11-23

First release. `analyze` now starts on Windows, and the README covers recording on Linux and Windows with ffmpeg, then analyzing the file.

### Added
- MIT license (#2)

### Added
- README: requirements, configuration, how it works, recording on Linux/Windows with ffmpeg + `analyze`, related projects (#8)

### Fixed
- `analyze` starts on Windows: the recorder (which needs Unix-only `termios`) is imported only by `record`/`run` (#6)

### Changed
- `.gitignore` aligned with the portfolio's common block: logs, Windows thumbnails, Sublime workspaces, shared `.vscode/extensions.json` (#4)

[Unreleased]: https://github.com/lucidbeaming/audio-screenshotter/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/lucidbeaming/audio-screenshotter/releases/tag/v1.0.0
