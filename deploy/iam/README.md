# IAM policies for the AgentCore Runtime deployment (step 4c)

Templates, with `${AWS_ACCOUNT_ID}`, `${AWS_REGION}` and
`${FIXIT_AGENTCORE_MEMORY_ID}` placeholders so no account id is committed.
Render filled-in copies with `make iam-policies` (written to
`build/iam/`, gitignored).

| File | Attach to | Purpose |
|---|---|---|
| `runtime-execution-trust.json` | Trust policy of role `FixItAgentCoreRuntimeRole` | Lets only AgentCore (in this account) assume it |
| `runtime-execution-policy.json` | Inline policy on `FixItAgentCoreRuntimeRole` | What the running container may do |
| `deployer-policy.json` | The IAM user/role that runs `scripts/push_image.py` / `scripts/deploy_runtime.py` | Push, deploy, invoke, tear down, read logs |

Deliberately **not** in the execution role, though AWS's sample role has them:
- `bedrock:InvokeModel*` -- the server never calls an LLM (CLAUDE.md rule 3).
- `bedrock-agentcore:GetWorkloadAccessToken*` -- runtimes created after
  2025-10-13 get these via the `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity`
  service-linked role, and FixIt uses no outbound auth.
