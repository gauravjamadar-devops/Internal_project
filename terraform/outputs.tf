output "dev_namespace" {
  description = "Kubernetes dev namespace created by Terraform"
  value       = kubernetes_namespace.dev.metadata[0].name
}

output "prod_namespace" {
  description = "Kubernetes prod namespace created by Terraform"
  value       = kubernetes_namespace.prod.metadata[0].name
}

output "dev_release_name" {
  description = "Helm release name for the dev environment"
  value       = helm_release.fastapi_dev.name
}

output "prod_release_name" {
  description = "Helm release name for the prod environment"
  value       = helm_release.fastapi_prod.name
}
