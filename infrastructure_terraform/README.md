# Baskt Terraform infrastructure

This project manages separate Baskt environments from environment-specific
Terraform roots. Shared module structure is duplicated under each root for now
so new environments can be introduced conservatively.

Each AWS resource still has its own Terraform file. Terraform automatically
combines all `.tf` files within each module folder.

```text
infrastructure_terraform/
├── dev/                    # Existing dev environment
│   └── modules/
│       ├── dynamodb/
│       ├── ecr/
│       ├── opensearch_domain/
│       ├── opensearch_indices/
│       ├── queues/
│       ├── search_indexers/
│       └── trade_worker/
└── test/                   # New test environment, test-* resources
    └── modules/
        ├── dynamodb/
        ├── ecr/
        ├── opensearch_domain/
        ├── opensearch_indices/
        ├── queues/
        ├── search_indexers/
        └── trade_worker/
```

## Existing-resource migration

The physical resource names match the current dev infrastructure. Import every
existing resource before the first apply. For example:

```bash
cd infrastructure_terraform/dev

terraform init \
  -backend-config="bucket=YOUR_TERRAFORM_STATE_BUCKET" \
  -backend-config="key=baskt/dev/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"

terraform import module.dynamodb.aws_dynamodb_table.baskt_account dev-baskt-account-dynamodb
terraform import module.dynamodb.aws_dynamodb_table.model_portfolio dev-model-portfolio-dynamodb
terraform import module.opensearch_domain.aws_opensearch_domain.model_portfolio_search dev-model-portfolio-search
```

Set `opensearch_endpoint_override` to the existing hostname during this initial
import so the OpenSearch provider can connect before the domain is represented
in Terraform state. It can be removed afterward.

Continue importing the queues, Lambdas, IAM roles, schedules, event-source
mappings, ECR repository, and remaining tables. Then run `terraform plan` and
resolve all unexpected drift before allowing GitHub to apply anything.

The test environment is intended to create new `test-*` resources. Initialize it
with a separate state key:

```bash
cd infrastructure_terraform/test

terraform init \
  -backend-config="bucket=YOUR_TERRAFORM_STATE_BUCKET" \
  -backend-config="key=baskt/test/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"
```

## GitHub workflow

Pushes to `develop` or `feature/**` run formatting, validation, `terraform plan`,
and `terraform apply` against the dev environment through GitHub OIDC:

```bash
terraform fmt -check -recursive
terraform init [backend configuration]
terraform validate
terraform plan -out=tfplan -var-file=dev.tfvars
terraform apply -auto-approve tfplan
```

Build and push the trade-worker image first, tag it with the Git commit SHA,
then pass that immutable URI as `trade_worker_image_uri`.

Non-dev stateful resources use `prevent_destroy`. An intentional replacement
requires a reviewed code change removing that protection, followed by a separate
apply.

## Dev teardown

The dev root is intentionally destroyable so the entire `dev-*` environment can
be removed when test becomes the active lower environment. To tear it down from
GitHub Actions, run **Deploy Dev Infrastructure with Terraform** manually with:

- `action`: `destroy`
- `confirm_destroy_dev`: `DELETE_DEV`

The workflow creates a `terraform plan -destroy` plan and applies that exact
plan. Before creating the destroy plan, it applies the current dev Cognito user
pool configuration so Cognito deletion protection is inactivated first. Cognito
deletion protection is disabled in the dev root, OpenSearch and DynamoDB
`prevent_destroy` guards are removed, and the dev ECR repository is set to
`force_delete` so stored images do not block teardown.

The GitHub role referenced by `AWS_TERRAFORM_ROLE_ARN` must also be allowed to
clean up IAM roles created by the dev root. At minimum, the role needs these IAM
actions scoped to the `dev-*` roles:

- `iam:DetachRolePolicy`
- `iam:ListInstanceProfilesForRole`
- `iam:DeleteRole`
- `iam:DeleteRolePolicy`
- `iam:GetRole`
- `iam:ListAttachedRolePolicies`
- `iam:ListRolePolicies`

Do not commit real `.tfvars` files if they contain secrets. Sensitive Terraform
input is still stored in Terraform state, so the state bucket must use
encryption, versioning, strict IAM access, and locking. Migrating runtime
secrets to AWS Secrets Manager is recommended before production.
