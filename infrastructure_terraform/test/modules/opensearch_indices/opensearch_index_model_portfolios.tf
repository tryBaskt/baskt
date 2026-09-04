resource "opensearch_index" "model_portfolios" {
  name               = "${var.environment}-model-portfolios-v1"
  number_of_shards   = "1"
  number_of_replicas = "0"
  mappings = jsonencode({
    properties = {
      portfolio_id = { type = "keyword" }
      portfolio_name = {
        type   = "text"
        fields = { keyword = { type = "keyword" } }
      }
      description                     = { type = "text" }
      portfolio_owner_cognito_user_id = { type = "keyword" }
      created_at                      = { type = "date" }
      updated_at                      = { type = "date" }
      visibility                      = { type = "keyword" }
    }
  })

  lifecycle {
    prevent_destroy = true
  }
}
