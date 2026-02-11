# Use python 3.9 slim as base
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Copy requirements files
COPY bot/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY bot/ bot/
# Copy the entrypoint we just created
COPY bot/docker_entrypoint.py bot/

# Run the python entrypoint
CMD ["python", "bot/docker_entrypoint.py"]
