# Preserve the backend image repository, secrets, certificate and DNS record.
# ECS tasks, the load balancer and their networking are retired by the same plan.
moved {
  from = module.backend_ecs
  to   = module.backend_lambda
}
