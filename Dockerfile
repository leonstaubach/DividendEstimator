FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY divvydiary_app ./divvydiary_app

EXPOSE 8080
CMD ["uvicorn", "divvydiary_app.web:app", "--host", "0.0.0.0", "--port", "8080"]
