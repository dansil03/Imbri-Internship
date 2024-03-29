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
    print(f"Checking existence for {entity_key} with value: {unique_value}")

    indirect_rel = config.get("indirect_relationships", {}).get(entity_key)
    print(f"Indirect relationship: {indirect_rel}")

    headers = {'Content-Type': 'application/json'}

    if indirect_rel:
        related_entity = indirect_rel["related_entity"]
        related_field = indirect_rel["related_field"]
        inverse_relation_field = indirect_rel["inverse_relation_field"]

        query = f"""
        {{
            var(func: eq({related_entity}.{related_field}, "{unique_value}")) {{
                ~{entity_key}.{inverse_relation_field} {{
                    contact_uids as uid
                }}
            }}
            entity(func: uid(contact_uids)) {{
                uid
            }}
        }}
        """
    else:
        unique_properties = config["unique_properties"][entity_key]
        if isinstance(unique_properties, str):
            unique_properties = [unique_properties]
            unique_values = [unique_value]  
        else:
            unique_values = unique_value  

        conditions = []
        for prop, val in zip(unique_properties, unique_values):
            conditions.append(f'eq({entity_key}.{prop}, "{val}")')

        query_condition = " AND ".join(conditions)

        query = f"""
        {{
            entity(func: {query_condition}) {{
                uid
            }}
        }}
        """

    try:
        response = requests.post(dgraph_query_url, headers=headers, data=json.dumps({'query': query}))
        if response.status_code == 200:
            result = response.json()
            entities = result.get('data', {}).get('entity', [])
            if entities:
                return True, [entity['uid'] for entity in entities]
            else:
                return False, []
        else:
            print(f"Error querying Dgraph: {response.status_code} - {response.text}")
            return False, []
    except Exception as e:
        print(f"Exception during Dgraph query: {e}")
        return False, []

def send_to_dgraph(nquads, dgraph_url):
    logging.info("Sending N-Quads data to Dgraph...")
    headers = {'Content-Type': 'application/rdf'}
    try:
        response = requests.post(dgraph_url, data=nquads, headers=headers)
    except Exception as e:
        traceback.print_exc()

def format_value(value):
    # Escape backslashes en dubbele aanhalingstekens
    escaped_value = value.replace("\\", "\\\\").replace("\"", "\\\"")

    # Vervang specifieke patronen zoals "_x000d_" met "\\r\\n" (carriage return + newline)
    escaped_value = escaped_value.replace('_x000d_\\n', '\\r\\n').replace('_x000d_', '\\r\\n')

    # Vervang newline en tab karakters
    escaped_value = escaped_value.replace('\n', '\\n').replace('\t', '\\t')

    # Controleer op URL's en formatteer als RDF string
    if 'http://' in escaped_value or 'https://' in escaped_value:
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

    for entity_key in ["Phone", "Email", "Contact", "User", "Organization", "Ticket"]:
        if entity_key in config["entity_definitions"]:

            print(f"Verwerken van entiteit: {entity_key}")

        
            item = apply_mappings(item, config, entity_key)
            

            entity_config = config["entity_definitions"][entity_key]
            unique_property = config["unique_properties"].get(entity_key)
            indirect_rel = config["indirect_relationships"].get(entity_key) 
            unique_value = None
            existing_uid = None

            if unique_property:
                if isinstance(unique_property, list):
                    unique_value = [item.get(config["api_to_property_mapping"].get(prop)) for prop in unique_property]
                    print(f"Unique value as list: {unique_value}")
                else:
                    unique_value = item.get(config["api_to_property_mapping"].get(unique_property))
                    print(f"Unique value as single value: {unique_value}")

                # Hier voegen we de controle op bestaande UID's weer toe
                if unique_value is not None:
                    existing_uid = entity_exists(entity_key, unique_value, dgraph_query_url)
                    print(f"Bestaande entity_id voor {entity_key}: {existing_uid}")

            elif indirect_rel: 
                print(f"Indirecte relatie gevonden voor {entity_key}") 
                related_entity = indirect_rel["related_entity"]
                print(f"Related entity: {related_entity}")
                related_field = indirect_rel["related_field"]
                print(f"Related field: {related_field}")
                inverse_relation_field = indirect_rel["inverse_relation_field"]
                print(f"Inverse relation field: {inverse_relation_field}")

                unique_value = item.get(config["api_to_property_mapping"].get(related_field))
                print(f"Unique value for indirect relationship: {unique_value}")

                if unique_value is not None:
                    existing_uid = entity_exists(entity_key, unique_value, dgraph_query_url)
                    print(f"Bestaande entity_id voor {entity_key}: {existing_uid}")

            else:
                print(f"Geen unieke eigenschap gedefinieerd voor {entity_key}")
                properties_to_check = entity_config.get("match_properties", [])

            if not existing_uid:
                entity_id = "_:_" + entity_config['prefix'] + str(uuid.uuid4())
                print(f"Nieuwe entity_id gegenereerd voor {entity_key}: {entity_id}")
            else:
                entity_id = f"<{existing_uid}>"

            entity_ids[entity_key] = entity_id

            if not existing_uid:
                nquads.append(f"{entity_id} <dgraph.type> \"{entity_key}\" .")

            for prop in entity_config.get("properties", {}).keys():
                api_field = config["api_to_property_mapping"].get(prop)
                if api_field in item and item[api_field] is not None:
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
    nquads_data = build_nquads_data(message.value, config, config['dgraph_mutation_url'])
    logging.info(f"Generated N-Quads Data:\n{nquads_data}")

    json_file_path = '/tmp/nquads.json'

    write_to_json_file(nquads_data, json_file_path)

    send_to_dgraph(nquads_data, config['dgraph_mutation_url'])

