# PowerShell script to create Jenkins ServiceAccount RBAC, extract secrets/certs, and assemble a standalone kubeconfig file

$ErrorActionPreference = "Stop"

$SA_NAME = "jenkins-sa"
$SECRET_NAME = "jenkins-sa-token"
$NAMESPACE = "default"
$KUBECONFIG_FILE = "jenkins-kubeconfig.conf"
$CLUSTER_NAME = "my-k8s-cluster"
$CONTEXT_NAME = "jenkins-context"

Write-Host "1. Applying Kubernetes ServiceAccount and RBAC..."
kubectl apply -f jenkins-rbac.yaml

Write-Host "2. Extracting Cluster Endpoint, CA Certificate, and Bearer Token..."
$SERVER_URL = (kubectl config view --raw -o jsonpath='{.clusters[0].cluster.server}')

# Wait up to 10 seconds for K8s token controller to populate secret token & ca.crt
$TOKEN_B64 = ""
$CA_DATA = ""
$retries = 0
while (([string]::IsNullOrEmpty($TOKEN_B64) -or [string]::IsNullOrEmpty($CA_DATA)) -and $retries -lt 10) {
    Start-Sleep -Seconds 1
    $CA_DATA = (kubectl get secret $SECRET_NAME -n $NAMESPACE -o jsonpath='{.data.ca\.crt}' 2>$null)
    $TOKEN_B64 = (kubectl get secret $SECRET_NAME -n $NAMESPACE -o jsonpath='{.data.token}' 2>$null)
    $retries++
}

if ([string]::IsNullOrEmpty($TOKEN_B64)) {
    Write-Error "Error: Token not retrieved from secret $SECRET_NAME."
}

$TOKEN = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($TOKEN_B64))

Write-Host "3. Constructing Kubeconfig: $KUBECONFIG_FILE..."

# Set cluster server URL
kubectl config --kubeconfig=$KUBECONFIG_FILE set-cluster $CLUSTER_NAME --server=$SERVER_URL

# Embed cluster CA certificate data
kubectl config --kubeconfig=$KUBECONFIG_FILE set clusters.$CLUSTER_NAME.certificate-authority-data $CA_DATA

# Set user credentials with SA token
kubectl config --kubeconfig=$KUBECONFIG_FILE set-credentials $SA_NAME --token=$TOKEN

# Connect user and cluster via context
kubectl config --kubeconfig=$KUBECONFIG_FILE set-context $CONTEXT_NAME --cluster=$CLUSTER_NAME --user=$SA_NAME --namespace=$NAMESPACE

# Set current context
kubectl config --kubeconfig=$KUBECONFIG_FILE use-context $CONTEXT_NAME

Write-Host "4. Validating Kubeconfig file..."
kubectl --kubeconfig=$KUBECONFIG_FILE get pods -n $NAMESPACE

Write-Host "=========================================================="
Write-Host "Successfully generated standalone kubeconfig: $KUBECONFIG_FILE"
Write-Host "You can upload this file into Jenkins Credentials (Secret file or Kubeconfig)."
Write-Host "=========================================================="
