FROM python:3.11.7-slim 

WORKDIR /app

COPY . .                               

RUN pip install --no-cache-dir -r requirements.txt 

CMD ["sh", "-c", "python Kafka-ProducerScript.py & python Kafka-ConsumerScript.py"]

