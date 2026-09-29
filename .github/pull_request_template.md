## What and why

## Checklist

- [ ] Tests added or updated (every change needs tests)
- [ ] `make lint` and `make format` are clean, `make test` passes
- [ ] No AWS account ids, memory/runtime ids, credentials or tokens (use `<account>`, `<memory-id>`, `<runtime-id>`)
- [ ] If a manual was added: `source_note` in the manifest says where the URL came from and why it is free, `make validate-manifest` passes, and no PDF is committed
- [ ] No LLM calls inside tool handlers; tool latency budget unaffected
