# Docs: make the Docker section of the README copy-pasteable end to end

## Description

Follow README's 'Running in Docker' section on a clean machine (x86_64 and, if you can, arm64) and fix whatever is unclear or wrong: when the QEMU step is needed, what `make docker-smoke` expects to be running, and the difference between `make docker-run` (SQLite volume) and `make docker-run-agentcore`. Note anything you had to guess.

## Acceptance criteria

- [ ] Every command in the section runs as written on your machine, or the section says when it does not apply.
- [ ] No AWS ids appear in the text; use `<memory-id>` and `<runtime-id>`.
- [ ] `make test` passes (a test guards the Dockerfile contract, so do not change the Dockerfile in this issue).

## Files to touch

- `README.md`
