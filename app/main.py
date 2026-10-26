from fastapi import FastAPI, HTTPException
import os
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter, Histogram
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware import Middleware
import time

tasks = []

# Define Prometheus metrics
request_count = Counter('app_requests_total', 'Total requests', ['method', 'endpoint', 'status'])
request_duration = Histogram('app_request_duration_seconds', 'Request duration', ['method', 'endpoint'])
task_count = Counter('app_tasks_total', 'Total tasks created', [])
# Dedicated error counter for easy PromQL querying in AI observability
error_count = Counter('app_http_errors_total', 'Total intentional HTTP 5xx errors', ['endpoint'])

# Middleware for automatic HTTP metrics
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        process_time = time.perf_counter() - start_time

        # Ensure labels are strings
        request_count.labels(
            method=request.method,
            endpoint=request.url.path,
            status=str(response.status_code)
        ).inc()

        request_duration.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(process_time)

        return response

# Register middleware at app creation
middleware = [
    Middleware(MetricsMiddleware)
]

app = FastAPI(middleware=middleware)

# Expose metrics endpoint
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
def health():
    if os.getenv("FAIL_HEALTH") == "true":
        raise HTTPException(status_code=500, detail="Simulated Failure")
    return {"status": "ok"}

# -----------------------------------------------------------------------
# DEV-ONLY: Controlled failure endpoint for observability testing.
# Guarded by ENABLE_SIMULATE_ERROR env var — NOT enabled in prod.
# Mirrors the FAIL_HEALTH guard pattern used above.
# -----------------------------------------------------------------------
@app.get("/simulate-error")
def simulate_error():
    if os.getenv("ENABLE_SIMULATE_ERROR") != "true":
        raise HTTPException(
            status_code=404,
            detail="Endpoint not available in this environment"
        )
    error_count.labels(endpoint="/simulate-error").inc()
    raise HTTPException(status_code=500, detail="Simulated 500 error for observability testing")

@app.get("/tasks")
def get_tasks():
    return {"tasks": tasks}

@app.post("/tasks")
def add_task(task: str):
    tasks.append(task)
    task_count.inc()
    return {"message": "Task added", "tasks": tasks}

@app.get("/config")
def config():
    return {
        "app_name": os.getenv("APP_NAME"),
        "environment": os.getenv("ENVIRONMENT")
    }
