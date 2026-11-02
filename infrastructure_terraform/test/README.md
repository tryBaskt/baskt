# Baskt test Terraform infrastructure

This root manages the Baskt test environment. Resources are named with the
`test-` prefix through `var.environment = "test"`.

Initialize this root with a state key that is separate from dev:

```bash
terraform init \
  -backend-config="bucket=trybaskt-terraform-state-499133675835" \
  -backend-config="key=baskt/test/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"
```

Use `test.tfvars.example` as the starting point for local plans. Do not commit a
real `.tfvars` file if it contains secrets or account-specific image URIs.

## Request-driven backend

The API runs as a container-based Lambda function behind a regional API Gateway
HTTP API at `https://api-test.trybaskt.com`. FastAPI still verifies Cognito tokens
and handles CORS. The frontend API URL and public route contracts stay the same.
The SQS trade worker remains a separate Lambda with its existing market-hours
controls.

The backend has no provisioned concurrency, warmer, ECS service, or load balancer.
Lambda can retain frozen execution environments between requests, but there is
no continuously billed API container. Cold starts add latency. API Gateway,
Secrets Manager, ECR, logs, and database usage have their own charges.

Build with `deployables/backend_lambda/Dockerfile` for `linux/amd64` and
`--provenance=false` so the pushed image has a Lambda-compatible single-platform
manifest. The Lambda Web Adapter
starts the existing Uvicorn server; cache directories use `/tmp` because the
rest of a Lambda container filesystem is read-only. At cold start,
`deployables/backend_lambda/lambda_startup.py` loads the two sandbox Alpaca secrets using the function's
execution role before starting Uvicorn. Terraform stores only their ARNs in the
backend environment. Rotated secret values are picked up by new execution
environments; deploy a new image/configuration to force a refresh when needed.

HTTP API requests have a hard **30-second integration timeout**, including cold
initialization that spills into invocation. Slow backtests/analytics and account
lifecycle requests must be verified against that limit. Do not automatically
retry mutations after a timeout: a broker-side action may have succeeded.
Longer operations should become asynchronous jobs if this limit is reached.

## Deploying the ECS-to-Lambda change

Run **Deploy Test Environment** from the updated revision using the existing
GitHub `test` environment configuration. The workflow tests the startup wrapper,
builds and pushes `test-backend:lambda-GIT_SHA`, updates the runtime secrets, and
passes that immutable image URI into Terraform before the infrastructure apply.
Older ECS images cannot be used for the Lambda function.

The module state move preserves the ECR repository, secret containers, ACM
certificate, and Route 53 record. The apply replaces the ECS service and ALB with
Lambda/API Gateway and updates the domain's alias. Expect a brief interruption
during the initial cutover and DNS propagation; this is not a zero-downtime
migration. The workflow retries the read-only health probe, then runs the
existing downstream tests. Unrelated obsolete search resources are retired only
after the health check when they are still present in state.

The GitHub Terraform role needs API Gateway management, Lambda image deployment,
ECR repository-policy management, and permission to pass the backend Lambda
execution role, in addition to its existing resource-management permissions.
Check the plan for unexpected stateful-resource replacement before applying
locally. No live resources are changed merely by editing these files.

Local checks:

```bash
python -m pytest --noconftest -o addopts= backend/tests_v2/test_lambda_startup.py -q
terraform -chdir=infrastructure_terraform/test fmt -check -recursive
terraform -chdir=infrastructure_terraform/test validate
```
