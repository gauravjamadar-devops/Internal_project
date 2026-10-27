FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for layer caching
COPY mcp-server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY mcp-server/ .

# Copy config
COPY config/config.yaml /app/config/config.yaml

EXPOSE 8080

# Kubernetes runs the server over Streamable HTTP; local clients can use stdio.
ENV MCP_CONFIG_PATH=/app/config/config.yaml
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080

CMD ["python", "main.py"]
