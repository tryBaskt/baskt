"""Auto-discover and provision dev resource modules."""

from importlib import import_module
from pkgutil import iter_modules

from aws_cdk import Stack
from constructs import Construct

import resources


class BasktDevStack(Stack):
    """Development stack whose resource modules are discovered automatically."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        state: dict[str, object] = {}

        modules = sorted(
            module.name
            for module in iter_modules(resources.__path__)
            if not module.name.startswith("_")
        )
        if not modules:
            raise RuntimeError("No infrastructure resource modules were discovered")

        for module_name in modules:
            module = import_module(f"resources.{module_name}")
            provision = getattr(module, "provision", None)
            if provision is None:
                raise RuntimeError(
                    f"Resource module resources.{module_name} has no provision()"
                )
            provision(self, state)
