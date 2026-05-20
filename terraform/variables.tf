variable "namespace_dev" {
  description = "Kubernetes namespace for the dev environment"
  type        = string
  default     = "dev"
}

variable "namespace_prod" {
  description = "Kubernetes namespace for the prod environment"
  type        = string
  default     = "prod"
}

variable "chart_path" {
  description = "Path to the Helm chart for the FastAPI application"
  type        = string
  default     = "../fastapi-chart"
}

variable "release_name_dev" {
  description = "Helm release name for dev environment"
  type        = string
  default     = "fastapi-dev"
}

variable "release_name_prod" {
  description = "Helm release name for prod environment"
  type        = string
  default     = "fastapi-prod"
}

variable "dev_values_file" {
  description = "Path to the dev values file"
  type        = string
  default     = "../environment/dev/values.yaml"
}

variable "prod_values_file" {
  description = "Path to the prod values file"
  type        = string
  default     = "../environment/prod/values.yaml"
}
