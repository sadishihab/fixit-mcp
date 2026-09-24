# IAM policies for the AgentCore Runtime deployment (step 4c)

Templates, with `${AWS_ACCOUNT_ID}`, `${AWS_REGION}` and
`${FIXIT_AGENTCORE_MEMORY_ID}` placeholders so no account id is committed.
Render filled-in copies with `make iam-policies` (written to
`build/iam/`, gitignored).

| File | Attach to | Purpose |
|---|---|---|
| `runtime-execution-trust.json` | Trust policy of role `FixItAgentCoreRuntimeRole` | Lets only AgentCore (in this account) assume it |
| `runtime-execution-policy.json` | Inline policy on `FixItAgentCoreRuntimeRole` | What the running container may do |
| `deployer-policy.json` | A **customer managed policy** `FixItRuntimeDeployer`, attached to the IAM user/role that runs `scripts/push_image.py` / `scripts/deploy_runtime.py` | Push, deploy, invoke, tear down, read logs |

Deliberately **not** in the execution role, though AWS's sample role has them:
- `bedrock:InvokeModel*` -- the server never calls an LLM (CLAUDE.md rule 3).
- `bedrock-agentcore:GetWorkloadAccessToken*` -- runtimes created after
  2025-10-13 get these via the `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity`
  service-linked role, and FixIt uses no outbound auth.

Size limits (IAM counts non-whitespace characters, so minifying doesn't help):
the deployer policy is too big to be an **inline user policy** (2,048
characters total across all of a user's inline policies), so it has to be a
customer managed policy (6,144 limit). `tests/unit/test_deploy_scripts.py`
checks every rendered file against the limit that applies to where it's
attached.
