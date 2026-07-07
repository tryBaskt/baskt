#!/usr/bin/env python3
"""CDK entry point for the existing Baskt development environment."""

import os

import aws_cdk as cdk

from baskt_dev_stack import BasktDevStack


app = cdk.App()
environment_name = app.node.try_get_context("environment") or "dev"
if environment_name != "dev":
    raise ValueError("This CDK application currently provisions only dev")

region = app.node.try_get_context("region") or os.getenv("CDK_DEFAULT_REGION", "us-east-1")
BasktDevStack(
    app,
    "BasktDev",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=region,
    ),
    description="Idempotent infrastructure for the Baskt development environment",
)
app.synth()
