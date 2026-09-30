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
| `observability-policy.json` | A **customer managed policy** `FixItObservability`, attached to `fixit-dev` (step 23b) | Create and delete the FixIt dashboard, the `fixit-*` alarms, the metric filters and 90-day log retention on the runtime's log group, and the `fixit-alerts` SNS topic with its email subscription; read metrics and alarms |

Deliberately **not** in the execution role, though AWS's sample role has them:
- `bedrock:InvokeModel*` -- the server never calls an LLM (CLAUDE.md rule 3).
- `bedrock-agentcore:GetWorkloadAccessToken*` -- runtimes created after
  2025-10-13 get these via the `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity`
  service-linked role, and FixIt uses no outbound auth.

Size limits (IAM counts non-whitespace characters, so minifying doesn't help):
the deployer policy is too big to be an **inline user policy** (2,048
characters total across all of a user's inline policies), so it has to be a
customer managed policy (6,144 limit).
`observability-policy.json` (about 1,060 characters rendered) is managed for
the same reason: `fixit-dev` already has inline policies sharing that one
2,048-character budget, and their total size wasn't readable from `fixit-dev`
itself (step 23a).

The observability plan it covers (step 23a; nothing is created yet): one
dashboard `FixIt`; metric filters on our `tool_call_completed`,
`tool_call_failed` and `agentcore_memory_call_failed` log lines; alarms
`fixit-errors` and `fixit-tool-latency` emailing through SNS topic
`fixit-alerts`; and **90-day retention** on the runtime's log group, which
currently never expires. Only the read statement uses `Resource: "*"`:
`ListMetrics`, `GetMetricData` and `ListDashboards` don't support
resource-level permissions, and `DescribeAlarms` sits with them so it can
list every alarm, not just `fixit-*`. `tests/unit/test_deploy_scripts.py`
checks every rendered file against the limit that applies to where it's
attached.
