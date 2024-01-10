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

dgraph_query_url = "http://internship-project-core-alpha-1:8080/query"

def entity_exists(entity_key, unique_value, dgraph_query_url):
    query = """
    {{
        entity(func: eq({}.{}, \"{}\")) {{
            uid
        }}
    }}
    """.format(entity_key, config["unique_properties"][entity_key], unique_value)

    print(f"Uitvoeren van query in entity_exists voor {entity_key} met waarde: {unique_value}")
    
    response = requests.post(dgraph_query_url, json={'query': query}, headers={'Content-Type': 'application/json'})
    if response.status_code == 200:
        result = response.json()
        print(f"Resultaat van entity_exists query: {result}")

        # Extract UID's from the nested structure
        entities = result.get('data', {}).get('queries', {}).get('entity', [])
        print(f"Entities: {entities}")

        if entities:
            first_entity_id = entities[0]['uid']
            print(f"Bestaande entity_id voor {entity_key}: {first_entity_id}")
            return first_entity_id
    else:
        print(f"Fout bij uitvoeren van query: {response.text}")
    return None




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

def build_nquads_data(item, config, dgraph_query_url):
    nquads = []
    entity_ids = {}

    for entity_key in ["Email", "Contact", "Organization", "Ticket"]:
        if entity_key in config["entity_definitions"]:
            print(f"Verwerken van entiteit: {entity_key}")

            entity_config = config["entity_definitions"][entity_key]
            unique_property = config["unique_properties"].get(entity_key)
            unique_value = None

            if unique_property:
                unique_value = item.get(config["api_to_property_mapping"].get(unique_property))
                print(f"Unieke waarde voor {entity_key}: {unique_value}")

                if unique_value is not None:
                    # Zoek naar bestaande UID
                    existing_uid = entity_exists(entity_key, unique_value, dgraph_query_url)
                    print(f"Bestaande entity_id voor {entity_key}: {existing_uid}")
                    if existing_uid:
                        # Gebruik bestaande UID met juiste syntax
                        entity_id = f"<{existing_uid}>"
                    else:
                        # Genereer nieuwe blank node
                        entity_id = "_:_" + entity_config['prefix'] + str(uuid.uuid4())
                        print(f"Nieuwe entity_id gegenereerd voor {entity_key}: {entity_id}")
                else:
                    # Geen unieke waarde gevonden
                    entity_id = None
                    print(f"Geen unieke waarde gevonden voor {entity_key}")
            else:
                # Geen unieke eigenschap gedefinieerd
                entity_id = None
                print(f"Geen unieke eigenschap gedefinieerd voor {entity_key}")

            if entity_id:
                entity_ids[entity_key] = entity_id

                if not existing_uid:
                    # Voeg dgraph.type alleen toe voor nieuwe entiteiten
                    nquads.append(f"{entity_id} <dgraph.type> \"{entity_key}\" .")

                for prop in entity_config.get("properties", {}).keys():
                    api_field = config["api_to_property_mapping"].get(prop)
                    if api_field in item and item[api_field] is not None:
                        value = str(item[api_field]).replace("_x000d_", "").replace("\"", "\\\"")
                        nquads.append(f"{entity_id} <{entity_key}.{prop}> \"{value}\" .")

                for related_entity_key, relation_predicate in entity_config.get("relations", {}).items():
                    related_entity_id = entity_ids.get(related_entity_key)
                    if related_entity_id:
                        nquads.append(f"{entity_id} <{entity_key}.{relation_predicate}> {related_entity_id} .")
                        print(f"Relatie toegevoegd: {entity_id} <{entity_key}.{relation_predicate}> {related_entity_id} .")

    final_nquads = "{ set { " + '\n'.join(nquads) + " } }"
    print("Gegenereerde N-Quads:")
    print(final_nquads)
    return final_nquads





consumer = KafkaConsumer(
    config['kafka_topic'],
    bootstrap_servers=config['kafka_server'],
    auto_offset_reset='earliest',
    group_id=config['kafka_consumer_group'],
    value_deserializer=lambda m: json.loads(m.decode('utf-8'))
)

for message in consumer:
    logging.info(f"Received message: {message.value}")
    nquads_data = build_nquads_data(message.value, config, config['dgraph_url'])
    logging.info(f"Generated N-Quads Data:\n{nquads_data}")
    send_to_dgraph(nquads_data, config['dgraph_url'])
