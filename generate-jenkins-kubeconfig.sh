#!/bin/bash
# Script to create Jenkins ServiceAccount RBAC, extract secrets/certs, and assemble a standalone kubeconfig file

set -e

SA_NAME="jenkins-sa"
SECRET_NAME="jenkins-sa-token"
NAMESPACE="default"
KUBECONFIG_FILE="jenkins-kubeconfig.conf"
CLUSTER_NAME="my-k8s-cluster"
CONTEXT_NAME="jenkins-context"

echo "1. Applying Kubernetes ServiceAccount and RBAC..."
kubectl apply -f jenkins-rbac.yaml

echo "2. Extracting Cluster Endpoint, CA Certificate, and Bearer Token..."
SERVER_URL=$(kubectl config view --raw -o jsonpath='{.clusters[0].cluster.server}')

TOKEN_B64=""
CA_DATA=""
retries=0
while ( [ -z "$TOKEN_B64" ] || [ -z "$CA_DATA" ] ) && [ $retries -lt 10 ]; do
  sleep 1
  CA_DATA=$(kubectl get secret ${SECRET_NAME} -n ${NAMESPACE} -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)
  TOKEN_B64=$(kubectl get secret ${SECRET_NAME} -n ${NAMESPACE} -o jsonpath='{.data.token}' 2>/dev/null || true)
  retries=$((retries + 1))
done

if [ -z "$TOKEN_B64" ]; then
  echo "Error: Token not retrieved. Verify secret creation."
  exit 1
fi

TOKEN=$(echo "$TOKEN_B64" | base64 --decode)

echo "3. Constructing Kubeconfig: ${KUBECONFIG_FILE}..."

# Set cluster server URL
kubectl config --kubeconfig=${KUBECONFIG_FILE} set-cluster ${CLUSTER_NAME} \
  --server=${SERVER_URL}

# Embed cluster CA certificate data
kubectl config --kubeconfig=${KUBECONFIG_FILE} set \
  clusters.${CLUSTER_NAME}.certificate-authority-data "${CA_DATA}"

# Set user credentials with SA token
kubectl config --kubeconfig=${KUBECONFIG_FILE} set-credentials ${SA_NAME} \
  --token=${TOKEN}

# Connect user and cluster via context
kubectl config --kubeconfig=${KUBECONFIG_FILE} set-context ${CONTEXT_NAME} \
  --cluster=${CLUSTER_NAME} \
  --user=${SA_NAME} \
  --namespace=${NAMESPACE}

# Set current context
kubectl config --kubeconfig=${KUBECONFIG_FILE} use-context ${CONTEXT_NAME}

echo "4. Validating Kubeconfig file..."
kubectl --kubeconfig=${KUBECONFIG_FILE} get pods -n ${NAMESPACE}

echo "=========================================================="
echo "Successfully generated standalone kubeconfig: ${KUBECONFIG_FILE}"
echo "You can upload this file into Jenkins Credentials (Secret file or Kubeconfig)."
echo "=========================================================="
