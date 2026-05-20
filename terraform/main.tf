resource "kubernetes_namespace" "dev" {
  metadata {
    name = var.namespace_dev
  }
}

resource "kubernetes_namespace" "prod" {
  metadata {
    name = var.namespace_prod
  }
}

resource "helm_release" "fastapi_dev" {
  name       = var.release_name_dev
  namespace  = kubernetes_namespace.dev.metadata[0].name
  chart      = var.chart_path
  values     = [file("${path.module}/${var.dev_values_file}")]
  create_namespace = false
  depends_on = [kubernetes_namespace.dev]
}

resource "helm_release" "fastapi_prod" {
  name       = var.release_name_prod
  namespace  = kubernetes_namespace.prod.metadata[0].name
  chart      = var.chart_path
  values     = [file("${path.module}/${var.prod_values_file}")]
  create_namespace = false
  depends_on = [kubernetes_namespace.prod]
}
