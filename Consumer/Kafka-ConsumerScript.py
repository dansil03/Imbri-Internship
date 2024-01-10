from kafka import KafkaConsumer, KafkaAdminClient
from kafka.errors import NoBrokersAvailable
from urllib.parse import quote
import json
import uuid
import logging
import traceback
import requests  
import time 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def wait_for_kafka(broker, max_retries=5, wait_time=5):
    """Wait until Kafka is available."""
    retries = 0
    while retries < max_retries:
        try:
            admin_client = KafkaAdminClient(bootstrap_servers=broker)
            admin_client.close()
            print("Kafka is available!")
            return
        except NoBrokersAvailable:
            print(f"Kafka is unavailable, waiting for {wait_time} seconds...")
            time.sleep(wait_time)
            retries += 1
    raise Exception("Kafka is unavailable after multiple attempts.")

wait_for_kafka('kafka:29092')

with open('config.json') as config_file:
    config = json.load(config_file)

def send_to_dgraph(nquads, dgraph_url):
    logging.info("Sending N-Quads data to Dgraph...")
    headers = {'Content-Type': 'application/rdf'}
    try:
        response = requests.post(dgraph_url, data=nquads, headers=headers)
        logging.info(f'Successfully added: {response.text}')
    except Exception as e:
        logging.error(f"An error occurred while sending data to Dgraph: {e}")
        traceback.print_exc()

def generate_nquad(entity_key, prop, value, entity_id):
    if 'http://' in value or 'https://' in value:
        value = f"<{value}>"
    else:
        value = f"\"{value}\""
    return f"{entity_id} <{entity_key}.{prop}> {value} ."

def build_nquads_data(item, config):
    nquads = []
    entity_ids = {}

    entity_order = ["Email", "Contact", "Organization", "Ticket"]
    for entity_key in entity_order:
        if entity_key in config["entity_definitions"]:
            entity_config = config["entity_definitions"][entity_key]
            entity_id = f"_:_{entity_config['prefix']}{uuid.uuid4()}"
            entity_ids[entity_key] = entity_id

            nquads.append(f"{entity_id} <dgraph.type> \"{entity_key}\" .")

            for prop in entity_config.get("properties", {}).keys():
                api_field = config["api_to_property_mapping"].get(prop)
                if api_field in item and item[api_field] is not None:
                    value = str(item[api_field]).replace("_x000d_", "")
                    nquads.append(generate_nquad(entity_key, prop, value, entity_id))

            for related_entity_key, relation_predicate in entity_config.get("relations", {}).items():
                related_entity_id = entity_ids.get(related_entity_key)
                if related_entity_id:
                    nquads.append(f"{entity_id} <{entity_key}.{relation_predicate}> {related_entity_id} .")

    return "{ set { " + '\n'.join(nquads) + " } }"

consumer = KafkaConsumer(
    config['kafka_topic'],
    bootstrap_servers=config['kafka_server'],
    auto_offset_reset='earliest',
    group_id=config['kafka_consumer_group'],
    value_deserializer=lambda m: json.loads(m.decode('utf-8'))
)

for message in consumer:
    logging.info(f"Received message: {message.value}")
    nquads_data = build_nquads_data(message.value, config)
    logging.info(f"Generated N-Quads Data:\n{nquads_data}")
    send_to_dgraph(nquads_data, config['dgraph_url'])
