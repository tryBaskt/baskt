resource "opensearch_index" "baskt_accounts" {
  name               = "${var.environment}-baskt-accounts-v1"
  number_of_shards   = "1"
  number_of_replicas = "0"
  analysis_normalizer = jsonencode({
    lowercase_normalizer = {
      type   = "custom"
      filter = ["lowercase"]
    }
  })
  mappings = jsonencode({
    properties = {
      cognito_user_id = { type = "keyword" }
      display_name = {
        type = "text"
        fields = {
          keyword = {
            type       = "keyword"
            normalizer = "lowercase_normalizer"
          }
        }
      }
      description   = { type = "text" }
      profile_image = { type = "keyword", index = false }
    }
  })

  lifecycle {
    # OpenSearch index mappings and shard settings are immutable for the existing
    # test index. Keep Terraform from planning a destructive replacement; reindex
    # into a new index/alias if these settings need to change later. Replica count
    # stays managed so the single-node test domain can return to green health.
    ignore_changes = [
      analysis_normalizer,
      mappings,
      number_of_shards,
    ]
    prevent_destroy = true
  }
}
