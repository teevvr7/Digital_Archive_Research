# AI GPU Server Scripts

This folder contains local copies of the active code running on your remote GPU server (Lightning AI Studio space).

## Synchronization Workflow
1. When changes are made to the python files in this folder (e.g. `remote_paddle_server.py`), copy/upload the modified files to your active Lightning AI Studio cloud environment.
2. Restart the FastAPI service on the remote server to apply settings.
