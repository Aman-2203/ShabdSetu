# Server socket
bind =  "unix:/run/gunicorn/gunicorn.sock"
# Workers
workers = 1
worker_class = "sync"

# Timeouts
timeout = 240
graceful_timeout = 30

# Logging
accesslog = "-"
errorlog = "-"


# Process naming
proc_name = "shabdsetu"

daemon=False