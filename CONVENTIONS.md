# Conventions

## Repository Layout

- Root contains add-on files: `config.json`, `Dockerfile`, `rootfs/`.
- Documentation files live at the repo root.

## Files

- `config.json`: Keep minimal; add settings only when required.
- `Dockerfile`: Use `BUILD_FROM` and keep build steps minimal.
- `rootfs/`: Add-on filesystem overlay. Add files only when a real service is introduced.

## Style

- Prefer short, declarative documentation.
- Avoid implementation details until functionality is added.
