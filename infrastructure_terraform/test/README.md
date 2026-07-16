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
