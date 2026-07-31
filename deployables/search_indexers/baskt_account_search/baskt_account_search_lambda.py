#!/usr/bin/env python3
"""Blocked manual deployment entrypoint.

Search indexer Lambda deployment is owned by Terraform and GitHub Actions.
This file remains only to fail closed for old manual commands.
"""

from __future__ import annotations

import argparse


def main() -> None:
    """Fail closed so deployables cannot mutate AWS outside Terraform."""
    parser = argparse.ArgumentParser(
        description=(
            "Manual deployment is disabled. Deploy this Lambda through "
            "infrastructure_terraform and the GitHub Actions workflows."
        )
    )
    parser.add_argument("--create", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--destroy", action="store_true", help=argparse.SUPPRESS)
    parser.parse_known_args()
    raise SystemExit(
        "Manual deployment is disabled. Use the Terraform GitHub Actions "
        "workflow for the target environment."
    )


if __name__ == "__main__":
    main()
