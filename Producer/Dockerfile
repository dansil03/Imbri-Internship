FROM python:3.11.7-slim 

WORKDIR /usr/src/app

COPY . .                               

RUN pip install --no-cache-dir -r requirements.txt 

CMD ["python", "./Kafka-ProducerScript.py"] 