# Internet Connection & Network Status Monitor

This project has two ways to use the monitor:

- `python network_monitor.py` opens the Tkinter desktop version.
- `python web_app.py` starts the browser-based version on `http://127.0.0.1:8000`.

The browser version is designed to be deployed as a small Python web service.
It uses only the Python standard library and the existing `network_monitor.py`
check implementation; no `pip install` is required.

## Deploy with GitHub and Render

1. Create a GitHub repository for this project. Keep it private if you do not
   want the source code to be publicly visible.
2. Add and push `web_app.py`, `network_monitor.py`, `templates/index.html`,
   `render.yaml`, and `.gitignore` to that repository.
3. Sign in to Render and choose **New → Blueprint**.
4. Connect the GitHub repository and deploy the service described by
   `render.yaml`.
5. When the deployment is ready, open the Render service URL and share that URL
   with your friend.

Render needs access to the repository to build the service. Anyone with the
deployed URL can use this demo, so do not add passwords, secrets, or private
information to it.

## Important cloud behavior

The web app's checks run from the cloud server. The displayed hostname, OS,
local IP, connectivity, and latency describe that server—not the computer or
network of the person visiting the page. The hosted demo does not expose the
server's MAC address. Its log and monitoring statistics are shared by visitors
and may reset when the cloud service restarts. To check a visitor's own network,
the desktop app must run on their computer.
