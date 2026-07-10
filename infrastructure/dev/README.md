# Baskt development infrastructure

The development environment is defined as desired state with AWS CDK. Repeated
deployments are idempotent: CloudFormation updates changed properties and leaves
unchanged resources alone.

```bash
cd infrastructure/dev
python -m pip install -r requirements-cdk.txt
cdk bootstrap
cdk diff
cdk deploy --require-approval broadening
```

Resource names intentionally match the existing `dev` resources. Before the
first deployment, run `cdk import BasktDev` and map every existing physical
resource to its matching CDK logical resource. Do not run `cdk deploy` against
unmanaged resources with the same names: CloudFormation cannot automatically
adopt them and the deployment will fail with an already-exists error.

Stateful resources use `RETAIN`. Review `cdk diff` whenever CloudFormation marks
a resource for replacement. DynamoDB stream settings live with their table
definitions in `baskt_dev_stack.py`; the standalone stream deployment script is
obsolete.

The older resource-specific `--create` scripts remain temporarily for migration
reference only. Once the existing resources have been imported and a no-change
`cdk diff` has been confirmed, remove those scripts from CI and use only CDK.
