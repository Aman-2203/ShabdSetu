# Server socket
bind = "0.0.0.0:8000"

# Workers
workers = 1
worker_class = "sync"

# Timeouts
timeout = 180
graceful_timeout = 30

# Logging
accesslog = "-"
errorlog = "-"

# Safety
    
# Process naming
proc_name = "shabdsetu"

daemon = False
