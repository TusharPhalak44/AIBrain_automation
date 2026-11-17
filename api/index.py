import os
import sys

# Ensure project root directory is in Python path for Vercel Serverless environment
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.app.api.server import create_app

# Instantiate FastAPI application without background daemons (watchdog/mt5 local process) on serverless
app = create_app(enable_lifespan_tasks=False)

