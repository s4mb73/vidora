"""
Convenience entry point so you can run the dashboard from the repo root:

    python run_dashboard.py

It listens on http://localhost:8080
"""

from dashboard.app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
