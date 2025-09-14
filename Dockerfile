# Use an official Python runtime as parent image
FROM python:3.11-slim

# Set environment variables
# Prevents Python from writing pyc files to disc and buffering stdout & stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create a directory for the app
WORKDIR /app

# Copy requirements first so layer is cached if no change
COPY requirements.txt .

# Install dependencies
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Expose port (Flask default is 5000)
EXPOSE 9732

# The command to run your app
# Modify if your entrypoint is different
CMD ["python", "app.py"]
