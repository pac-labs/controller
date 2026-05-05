from __future__ import annotations

import os
import sys
import uvicorn

if __name__ == "__main__":
    host = os.environ.get("PI_AGENT_HOST", "0.0.0.0")
    port = int(os.environ.get("PI_AGENT_PORT", "443"))
    uvicorn.run("pi_agent_platform.api.main:app", host=host, port=port)
