resource "opensearch_index" "baskt_accounts" {
  name               = "${var.environment}-baskt-accounts"
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

}
