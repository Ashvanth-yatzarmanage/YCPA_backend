import os

import uvicorn

if __name__ == "__main__":
    reload = os.getenv("RELOAD", "true").lower() == "true"
    uvicorn.run(
        "ycpa.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=reload,
        # Only watch source code, not logs/ or other generated files,
        # otherwise the reloader picks up its own log output in a loop.
        reload_dirs=["ycpa"] if reload else None,
    )
