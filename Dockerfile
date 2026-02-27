FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY om_server.py generate_om.py ./
COPY assets/ ./assets/
EXPOSE 8080
CMD ["python3", "om_server.py", "8080"]
