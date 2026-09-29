# Security policy

## Reporting a vulnerability

Please report security issues privately, not in a public issue or pull request.
Use GitHub's "Report a vulnerability" (Security tab, private advisory) on this
repository. Include what you found, how to reproduce it, and the impact. You
should get an acknowledgement within a few days; this is a small project, so
please be patient.

## Scope and data

FixIt handles **no real customer data**. Households and appliances in the demo
are synthetic seed data, and the manuals are public manufacturer documents. The
deployed server currently uses IAM (SigV4) inbound auth only; OAuth account
linking is not built yet.

## Credentials

Never commit credentials: AWS keys, tokens, `.env` files, AWS account ids, or
AgentCore memory/runtime ids. Use `<account>`, `<memory-id>`, `<runtime-id>` in
docs. A test (`tests/unit/test_no_account_ids.py`) fails the build on these ids
in tracked files. If you committed a secret by mistake, treat it as leaked:
revoke and rotate it first, then remove it from the repository.
