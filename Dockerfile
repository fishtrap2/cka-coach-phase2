# -----------------------------------------------------------------------------
# cka-coach Dockerfile
#
# Purpose:
#   Build a runnable container image for the Phase 1 cka-coach prototype.
#
# What this image does:
#   - installs Python
#   - installs the Python dependencies from requirements.txt
#   - copies the cka-coach source code into the image
#   - starts the Streamlit dashboard on port 8501
#
# Why this matters in Kubernetes:
#   A container image is the packaged application artifact.
#   Kubernetes does not run your source tree directly.
#   Instead, Kubernetes pulls an image and starts a container from it.
#
# Mental model:
#   source code  ->  Docker image  ->  container  ->  Pod  ->  Kubernetes
#
# In cka-coach terms:
#   this is how the learning system itself "lives somewhere" inside the cluster.
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# 1) Choose a base image
#
# We start from an official Python runtime image.
#
# Why python:3.11-slim?
#   - official and widely used
#   - smaller than the full Python image
#   - good balance of compatibility and size
#   - enough for Streamlit + API client + Kubernetes Python client
#
# "slim" means:
#   a reduced Debian-based image with fewer extra packages installed.
#   This helps reduce image size and attack surface.
# -----------------------------------------------------------------------------
FROM python:3.11-slim


# -----------------------------------------------------------------------------
# 2) Set environment variables
#
# ENV writes environment variables into the image.
#
# PYTHONDONTWRITEBYTECODE=1
#   Prevents Python from writing .pyc bytecode files to disk.
#   This keeps the container a bit cleaner and avoids unnecessary files.
#
# PYTHONUNBUFFERED=1
#   Makes Python log/output appear immediately instead of being buffered.
#   Very useful in containers because we want logs to show up right away.
#
# PIP_NO_CACHE_DIR=1
#   Tells pip not to keep its package cache after installs.
#   This reduces image size.
#
# STREAMLIT_SERVER_PORT=8501
#   Streamlit's default port. We set it explicitly for clarity.
#
# STREAMLIT_SERVER_ADDRESS=0.0.0.0
#   This is very important in containers.
#   If Streamlit binds only to localhost (127.0.0.1), it will not be reachable
#   from outside the container.
#   Binding to 0.0.0.0 means "listen on all interfaces".
# -----------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0


# -----------------------------------------------------------------------------
# 3) Set the working directory inside the image
#
# WORKDIR creates the directory if it does not exist and makes it the default
# location for the next Docker instructions.
#
# Think of /app as:
#   "the root of the application inside the container"
#
# After this line:
#   - COPY . . will copy files into /app
#   - CMD commands will run from /app
# -----------------------------------------------------------------------------
WORKDIR /app


# -----------------------------------------------------------------------------
# 4) Install minimal OS packages
#
# Some Python applications need a few operating system tools.
# Here we install curl so we can use it in a container HEALTHCHECK.
#
# apt-get update
#   refreshes the package index
#
# apt-get install -y --no-install-recommends curl
#   installs curl without lots of extra recommended packages
#
# rm -rf /var/lib/apt/lists/*
#   cleans up package metadata afterwards to keep the image smaller
#
# Note:
#   If cka-coach later needs build tools or system libraries, they would be
#   added here. Keep this section minimal unless you truly need more.
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*


# -----------------------------------------------------------------------------
# 5) Copy dependency manifest first
#
# We copy requirements.txt before copying the full source tree.
#
# Why?
#   Docker builds in layers.
#   If requirements.txt has not changed, Docker can often reuse the cached layer
#   for "pip install -r requirements.txt" instead of reinstalling everything.
#
# This makes rebuilds much faster during development.
# -----------------------------------------------------------------------------
COPY requirements.txt .


# -----------------------------------------------------------------------------
# 6) Install Python dependencies
#
# First:
#   pip install --upgrade pip
#   updates pip itself
#
# Then:
#   pip install -r requirements.txt
#   installs the application dependencies
#
# These are the Python packages your app needs in order to run.
# -----------------------------------------------------------------------------
RUN pip install --upgrade pip && \
    pip install -r requirements.txt


# -----------------------------------------------------------------------------
# 7) Copy the rest of the application source code
#
# This copies everything from the repository root into /app inside the image.
#
# Because our Dockerfile lives at the root of cka-coach, this includes:
#   - src/
#   - ui/
#   - docs/   (if not excluded by .dockerignore)
#   - README.md
#   - any other files in the repo
#
# Important:
#   You should use a .dockerignore file so you do NOT copy unnecessary things
#   like:
#     - venv/
#     - .git/
#     - __pycache__/
#     - local secrets
# -----------------------------------------------------------------------------
COPY . .


# -----------------------------------------------------------------------------
# 8) Document the port the container listens on
#
# EXPOSE does not actually publish the port by itself.
# It serves as metadata/documentation that the containerized app expects to use
# port 8501.
#
# When running locally, you still need:
#   docker run -p 8501:8501 ...
#
# In Kubernetes, this helps you remember what containerPort to declare.
# -----------------------------------------------------------------------------
EXPOSE 8501


# -----------------------------------------------------------------------------
# 9) Define a health check
#
# HEALTHCHECK lets Docker periodically test whether the app is responding.
#
# Streamlit exposes a health endpoint at:
#   /_stcore/health
#
# This command:
#   - tries to fetch the health URL
#   - exits successfully if it works
#   - exits with failure if it does not
#
# Why useful?
#   - helps during local container testing
#   - gives a basic liveness signal
#
# Note:
#   In Kubernetes, you would usually also define livenessProbe/readinessProbe
#   directly in the Pod or Deployment manifest.
# -----------------------------------------------------------------------------
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1


# -----------------------------------------------------------------------------
# 10) Define the default process that runs when the container starts
#
# We use JSON-array exec form:
#   CMD ["streamlit", "run", "ui/dashboard.py"]
#
# Why this form is preferred:
#   - clearer signal handling
#   - avoids shell interpretation issues
#   - better container practice
#
# This tells the container to start the Streamlit dashboard from your repo:
#   ui/dashboard.py
#
# Since WORKDIR is /app, Docker will look for:
#   /app/ui/dashboard.py
#
# If later you want to run the CLI version instead, you would change CMD.
# -----------------------------------------------------------------------------
CMD ["streamlit", "run", "ui/dashboard.py"]
