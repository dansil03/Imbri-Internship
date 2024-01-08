from kafka import KafkaConsumer, KafkaAdminClient
from kafka.errors import NoBrokersAvailable
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

def priority_mapping(priority):
    return {
        5: "Low",
        4: "Medium",
        3: "Medium",
        2: "High",
        1: "Critical"
    }.get(priority, "Unknown")

def status_mapping(status):
    return {
        "Gesloten": "Closed",
        "Open": "Open"
    }.get(status, "Unknown")

def send_to_dgraph_http(item):
    existing_uid = item.get('existing_uid') # Verkrijg de UID van het bestaande record (als het bestaat) 
    if existing_uid: 
        uid = existing_uid 
        print('Existing Ticket UID:', uid) 
    else: 
        uid = f"_:ticket{uuid.uuid4()}"

    print("Preparing to send data to Dgraph via HTTP...")
    url = 'http://internship-project-core-alpha-1:8080/mutate?commitNow=true'  # Pas dit aan naar je Dgraph Alpha-adres
    mutation_data = {
        "uid": uid,
        "dgraph.type": "Ticket",
        "Ticket.organization_id": {
            "uid": "_:organization1", 
            "dgraph.type": "Organization", 
            "Organization.organization_name": item["Gebouw"], 
            "Organization.organization_type": "Hospital", 
            "Organization.contact_details": {
                "uid": "_:contact1", 
                "dgraph.type": "Contact", 
                "Contact.email": {
                    "uid": "_:email1",
                    "dgraph.type": "Email", 
                    "Email.email_address": item["E-mailadres melder"] 
                }, 
                "Contact.phone": { 
                    "uid": "_:phone1", 
                    "dgraph.type": "Phone", 
                    "Phone.phone_number": item["Telefoon"] 
                }
            }
        },
        "Ticket.issue_number": item['Code'], 
        "Ticket.issue_type": item['Incidentsoort'],
        "Ticket.issue_description": item['Omschrijving'],
        "Ticket.reported_by": {
            "username": item['Melder']
        },
        "Ticket.reported_at": item['Melddatum'],
        "Ticket.priority": priority_mapping(int(item['Prioriteit'])),
        "Ticket.ticket_status": status_mapping(item['Voortgangsstatus']),
        "Ticket.due_date": item["Gepl. gereeddatum"],
        "Ticket.closed_at": item["Werkelijk gereed"],
        "Ticket.resolution": item["Oplossing"],
        "Ticket.attributes": [
            {"attribute_name": "Impact", "attribute_value": item['Impact']},
            {"attribute_name": "Urgentie", "attribute_value": item['Urgentie']},
            {"attribute_name": "Vakgroep", "attribute_value": item['Vakgroep']},
        ]
    }

    mutation = json.dumps({"set": [mutation_data]})

    with open("last_mutation.json", "w") as file:
        file.write(mutation)

    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, data=mutation, headers=headers)
        print(f'Successfully added: {response.text}')
    except Exception as e:
        print(f"An error occurred while sending data to Dgraph: {e}")
        traceback.print_exc()

consumer = KafkaConsumer(
    'UltimoData',
    bootstrap_servers= 'kafka:29092', #['internship-project-kafka-1:9092'], #['localhost:29092'],
    auto_offset_reset='earliest',
    group_id='Ultimo_Group',
    value_deserializer=lambda m: json.loads(m.decode('utf-8'))
)


#dgraph_client = None  # Je hebt dit niet meer nodig

for message in consumer:
    print(f"Received message: {message.value}")
    send_to_dgraph_http(message.value)  # Gebruik de nieuwe functie

