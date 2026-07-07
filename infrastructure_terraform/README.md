# Baskt dev Terraform infrastructure

This project manages only the existing Baskt development environment. Related
resources live in reusable child modules, and the deployable root is
`environments/dev`.

Each AWS resource still has its own Terraform file. Terraform automatically
combines all `.tf` files within each module folder.

```text
infrastructure_terraform/
├── environments/dev/       # Backend, providers, inputs, and module composition
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
cd infrastructure_terraform/environments/dev

terraform init \
  -backend-config="bucket=YOUR_TERRAFORM_STATE_BUCKET" \
  -backend-config="key=baskt/dev/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"

terraform import module.dynamodb.aws_dynamodb_table.baskt_account dev_baskt_account_dynamodb
terraform import module.dynamodb.aws_dynamodb_table.model_portfolio dev_model_portfolio_dynamodb
terraform import module.opensearch_domain.aws_opensearch_domain.model_portfolio_search dev-model-portfolio-search
```

Set `opensearch_endpoint_override` to the existing hostname during this initial
import so the OpenSearch provider can connect before the domain is represented
in Terraform state. It can be removed afterward.

Continue importing the queues, Lambdas, IAM roles, schedules, event-source
mappings, ECR repository, and remaining tables. Then run `terraform plan` and
resolve all unexpected drift before allowing GitHub to apply anything.

## GitHub workflow

Pull requests run formatting, validation, and `terraform plan`. A merge into
`dev` assumes an AWS role through GitHub OIDC and applies the reviewed plan:

```bash
terraform fmt -check -recursive
terraform init [backend configuration]
terraform validate
terraform plan -out=tfplan -var-file=dev.tfvars
terraform apply -auto-approve tfplan
```

Build and push the trade-worker image first, tag it with the Git commit SHA,
then pass that immutable URI as `trade_worker_image_uri`.

Stateful resources use `prevent_destroy`. An intentional replacement requires a
reviewed code change removing that protection, followed by a separate apply.

Do not commit `dev.tfvars` if it contains secrets. Sensitive Terraform input is
still stored in Terraform state, so the state bucket must use encryption,
versioning, strict IAM access, and locking. Migrating runtime secrets to AWS
Secrets Manager is recommended before production.
