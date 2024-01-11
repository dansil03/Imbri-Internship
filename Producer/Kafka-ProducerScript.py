from confluent_kafka import Producer, KafkaError
import requests
from time import sleep
import json
import logging

logging.basicConfig(level=logging.INFO)

with open('config.json') as config_file:
    config = json.load(config_file)

def wait_for_service(url, max_retries=5, wait_time=5, check_func=None):
    """Wait until a service is available."""
    retries = 0
    while retries < max_retries:
        try:
            if check_func and check_func(url):
                print(f"{url} is available!")
                return
            else:
                print(f"{url} is not ready. Waiting...")
        except Exception as e:
            print(f"Error connecting to {url}: {e}, waiting for {wait_time} seconds...")

        sleep(wait_time)
        retries += 1
        print(f"Attempt {retries}/{max_retries}...")

    raise Exception(f"{url} is unavailable after multiple attempts.")

def fetch_api_data(api_url):
    print("Fetching API data...")
    response = requests.get(api_url)
    if response.status_code == 200:
        print("API data successfully fetched.")
        return response.json()
    else:
        print("Error fetching data: Status code", response.status_code)
        return None

def send_to_kafka(data, producer, topic):
    try:
        if data:
            serialized_data = json.dumps(data).encode('utf-8')
            producer.produce(topic, value=serialized_data)
            producer.poll(0)
            logging.info(f"Data successfully sent to Kafka topic: {topic}")
    except KafkaError as e:
        logging.error(f"Error sending data to Kafka topic: {topic}. Error: {e}")

def main():
    producer_conf = {
        'bootstrap.servers': config['kafka_server'],
        'acks': 'all',
        'retries': 5,
        'enable.idempotence': True
    }
    producer = Producer(producer_conf)

    wait_for_service(config['dgraph_url'], check_func=lambda url: requests.get(f"{url}/health").status_code == 200)
    wait_for_service(config['kafka_server'], check_func=lambda url: True)  # Simple check, adjust if necessary

    while True:
        data = fetch_api_data(config['api_url'])
        if data:
            for record in data:
                send_to_kafka(record, producer, config['kafka_topic'])

        producer.flush()  # Wait for all messages to be delivered

        print("Sleeping for 20 seconds...")
        sleep(20)  # Wait 20 seconds before fetching data again

if __name__ == "__main__":
    print("Starting Kafka producer...")
    main()
