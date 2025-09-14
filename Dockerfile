# Use an official Python runtime as parent image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY . .

# Expose Flask/Gunicorn port
EXPOSE 9732

# Run with Gunicorn using your preferred config
CMD ["gunicorn", "app:app", \
     "-b", "0.0.0.0:9732", \
     "--workers", "2", \
     "--threads", "16", \
     "--worker-class", "gthread", \
     "--timeout", "3600", \
     "--graceful-timeout", "90"]
