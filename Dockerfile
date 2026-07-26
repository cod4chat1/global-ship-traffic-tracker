FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .[google] playwright==1.52.0
COPY . .
ENV PYTHONPATH=/app/src
ENV SHIP_TRAFFIC_SKIP_WORKBOOK=1
ENTRYPOINT ["python", "-m", "ship_traffic.cli"]
CMD ["run", "--provider", "portwatch", "--google"]
