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
    unique_properties = config["unique_properties"][entity_key]
    if isinstance(unique_properties, str):
        unique_properties = [unique_properties]
        unique_values = [unique_value]  
    else:
        unique_values = unique_value  

    conditions = []
    for prop, val in zip(unique_properties, unique_values):
        conditions.append('eq({}.{}, "{}")'.format(entity_key, prop, val))

    query_condition = " AND ".join(conditions)

    query = """
    {{
        entity(func: {}) {{
            uid
        }}
    }}
    """.format(query_condition)

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


def entity_exists_based_on_properties(entity_key, item, config, dgraph_query_url):
    entity_config = config["entity_definitions"].get(entity_key, {})
    match_properties = entity_config.get("match_properties", [])

    print (f"Match properties: {match_properties}")

    print("Huidige item data:", item)

    if not match_properties:
        print("Geen match-eigenschappen gedefinieerd voor deze entiteit")
        return None

    filters = []
    for prop in match_properties:
        if prop in item:
            value = item[prop]
            filters.append(f'anyofterms({entity_key}.{prop}, "{value}")')

    print(f"Filters: {filters}")

    if not filters:
        print("Geen overeenkomende data gevonden in het item") 
        return None

    filter_query = " @filter(" + " AND ".join(filters) + ")"
    query = f"""
    {{
        entity(func: has({entity_key}.{match_properties[0]})){filter_query} {{
            uid
        }}
    }}
    """

    print(f"Uitvoeren van query in entity_exists_based_on_properties voor {entity_key} met filters: {filters}") 

    response = requests.post(dgraph_query_url, json={'query': query}, headers={'Content-Type': 'application/json'})

    print (f"Response: {response}")


    if response.status_code == 200:
        result = response.json()
        entities = result.get('data', {}).get('entity', [])
        if entities:
            return entities[0]['uid']
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

def format_value(value):
    # Vervang eerst alle backslashes met dubbele backslashes
    escaped_value = value.replace("\\", "\\\\")

    # Vervang nu '_x000d_' met '\\n' voor newline karakters
    escaped_value = escaped_value.replace('_x000d_', '\\n')

    escaped_value = escaped_value.replace('\n', ' ')

    if 'http://' in value or 'https://' in value:
        rdf_string = f'"{escaped_value}"^^<http://www.w3.org/2001/XMLSchema#string>'
    else:
        rdf_string = f'"{escaped_value}"' 

    return rdf_string


def generate_nquad(entity_key, prop, value, entity_id):
    return f'{entity_id} <{entity_key}.{prop}> {value} .'

def apply_mappings(item, config, entity_key):
    print(f"Applying mappings for entity: {entity_key}")
    # Retrieve mapping properties for the specific entity from the config
    mapping_properties = config["mapping_properties"].get(entity_key, [])
    # Retrieve actual mappings for the specific entity from the config
    entity_mappings = config["mappings"].get(entity_key, {})

    # Iterate over the list of mapping properties for this entity
    for map_prop in mapping_properties:
        # Get the API field corresponding to the mapping property
        api_field = config["api_to_property_mapping"].get(map_prop)
        # Check if the API field is in the item
        if api_field in item:
            # Get the value from the item for the mapping
            item_value = str(item[api_field])
            print(f"Original value for {map_prop} (field {api_field}): {item_value}")
            # Apply the mapping if it exists
            if item_value in entity_mappings.get(map_prop, {}):
                # Replace the item's original value with the mapped value
                item[api_field] = entity_mappings[map_prop][item_value]
                print(f"Mapped value for {map_prop}: {item[api_field]}")

    # Return the item with mappings applied
    return item

def build_nquads_data(item, config, dgraph_query_url):
    nquads = []
    entity_ids = {}

    for entity_key in ["Phone", "Email", "Contact","User", "Organization", "Ticket"]:
        if entity_key in config["entity_definitions"]:

            print(f"Verwerken van entiteit: {entity_key}")

            print(f"Voor apply_mappings, item: {item}")
            item = apply_mappings(item, config, entity_key)
            print(f"Na apply_mappings, item: {item}")

            entity_config = config["entity_definitions"][entity_key]
            unique_property = config["unique_properties"].get(entity_key)
            unique_value = None
            existing_uid = None

            if unique_property:
                if isinstance(unique_property, list):
                # Als unique_property een lijst is, haal alle waarden op
                    unique_value = [item.get(config["api_to_property_mapping"].get(prop)) for prop in unique_property]
                else:
                # Als unique_property geen lijst is, verwerk het als een enkele waarde
                    unique_value = item.get(config["api_to_property_mapping"].get(unique_property))
            else:
                # Voor entiteiten zonder unieke eigenschap
                print(f"Geen unieke eigenschap gedefinieerd voor {entity_key}")
                properties_to_check = entity_config.get("match_properties", [])
                print(f"Properties to check: {properties_to_check}")

            if not existing_uid:
                # Genereer nieuwe blank node
                entity_id = "_:_" + entity_config['prefix'] + str(uuid.uuid4())
                print(f"Nieuwe entity_id gegenereerd voor {entity_key}: {entity_id}")
            else:
                # Gebruik bestaande UID met juiste syntax
                entity_id = f"<{existing_uid}>"

            entity_ids[entity_key] = entity_id

            if not existing_uid:
                # Voeg dgraph.type alleen toe voor nieuwe entiteiten
                nquads.append(f"{entity_id} <dgraph.type> \"{entity_key}\" .")

            for prop in entity_config.get("properties", {}).keys():
                api_field = config["api_to_property_mapping"].get(prop)
                if api_field in item and item[api_field] is not None:
                    # Gebruik de format_value functie om de waarde correct te formatteren
                    value = format_value(str(item[api_field]))
                    nquads.append(generate_nquad(entity_key, prop, value, entity_id))

            for related_entity_key, relation_predicate in entity_config.get("relations", {}).items():
                related_entity_id = entity_ids.get(related_entity_key)
                if related_entity_id:
                    nquads.append(f"{entity_id} <{entity_key}.{relation_predicate}> {related_entity_id} .")

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

def write_to_json_file(data, file_path):
    with open(file_path, 'a') as file:
        json.dump(data, file)
        file.write('\n')

for message in consumer:
    logging.info(f"Received message: {message.value}")
    nquads_data = build_nquads_data(message.value, config, config['dgraph_url'])
    logging.info(f"Generated N-Quads Data:\n{nquads_data}")

    json_file_path = '/tmp/nquads.json'

    write_to_json_file(nquads_data, json_file_path)

    send_to_dgraph(nquads_data, config['dgraph_url'])
