#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash prepare_search_state.sh <initialized Terraform root>" >&2
  exit 1
fi

terraform_root="$1"
state_addresses="$(terraform -chdir="$terraform_root" state list)"
obsolete_addresses=()

while IFS= read -r address; do
  case "$address" in
    module.opensearch_indices.opensearch_index.*|module.search_indexers.data.archive_file.*)
      obsolete_addresses+=("$address")
      ;;
  esac
done <<< "$state_addresses"

if [[ ${#obsolete_addresses[@]} -eq 0 ]]; then
  echo "No obsolete search index state remains."
  exit 0
fi

# Index documents disappear with the domain; keep AWS resources tracked for deletion.
terraform -chdir="$terraform_root" state rm -lock-timeout=5m "${obsolete_addresses[@]}"
