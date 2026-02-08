# Server socket
bind =  "unix:/run/gunicorn/gunicorn.sock"
# Workers
workers = 1
worker_class = "sync"

# Timeouts
timeout = 180
graceful_timeout = 30

# Logging
accesslog = "-"
errorlog = "-"

# Safety - Memory Management
# Recycle worker after 100 requests to release accumulated memory
max_requests = 100
max_requests_jitter = 10

# Process naming
proc_name = "shabdsetu"

daemon=False