from confluent_kafka import Producer, KafkaError, KafkaException
import pydgraph 
import json
import requests
from time import sleep
import logging
from kafka.errors import NoBrokersAvailable
from confluent_kafka.admin import AdminClient

logging.basicConfig(level=logging.INFO)

api_url = "http://192.168.2.38:3000/api/ultimo-data"  # API URL to fetch data from
dgraph_url = "http://internship-project-core-alpha-1:8080" # Dgraph server URL 
kafka_topic = 'UltimoData'  # Kafka topic to send data to
kafka_server = 'kafka:29092' #'internship-project-kafka-1:9092' #'localhost:29092'  # Kafka server to connect to

def wait_for_kafka(broker, max_retries=5, wait_time=5):
    """Wait until Kafka is available and ready to handle requests."""
    retries = 0
    admin_client = AdminClient({'bootstrap.servers': broker})

    while retries < max_retries:
        try:
            # Fetch cluster metadata
            metadata = admin_client.list_topics(timeout=10)
            
            # If we can list topics, Kafka is considered available
            if metadata.topics:
                print("Kafka is available!")
                return
            else:
                print("Kafka is up but not ready to accept connections. Waiting...")

        except KafkaException as e:
            # Handle Kafka errors (e.g., connection failures)
            print(f"Kafka error: {e}, waiting for {wait_time} seconds...")
        
        except Exception as e:
            # Handle other potential exceptions (e.g., operational errors)
            print(f"Unexpected error: {e}, waiting for {wait_time} seconds...")

        # Wait before retrying
        sleep(wait_time)
        retries += 1
        print(f"Retry {retries}/{max_retries}...")

    raise Exception("Kafka is unavailable after multiple attempts.")

def wait_for_dgraph(dgraph_url, max_retries=5, wait_time=5):
    """Wait until the Dgraph server is ready to accept requests."""
    retries = 0
    while retries < max_retries:
        try:
            # Replace this with the appropriate health check or query endpoint for Dgraph
            response = requests.get(f"{dgraph_url}/health")
            if response.status_code == 200:
                print("Dgraph is available!")
                return
            else:
                print(f"Dgraph is not ready, status code: {response.status_code}. Waiting...")
        except requests.exceptions.RequestException as e:
            print(f"Failed to connect to Dgraph: {e}, waiting for {wait_time} seconds...")

        sleep(wait_time)
        retries += 1
        print(f"Retry {retries}/{max_retries}...")

    raise Exception("Dgraph is unavailable after multiple attempts.")


wait_for_kafka(kafka_server)

wait_for_dgraph(dgraph_url)

# Initialize a Kafka Producer with server details and a JSON serializer
producer_conf = {
    'bootstrap.servers': kafka_server,
   # 'value.serializer': lambda v: json.dumps(v).encode('utf-8'),
    'acks': 'all',  # Ensure all replicas acknowledge
    'retries': 5,  # Set retries to a higher number
    'enable.idempotence': True  # Enable idempotence
}

producer = Producer(producer_conf)


def priority_mapping(priority_num):
    mapping = {
        1: "Critical",
        2: "High",
        3: "Medium",  
        4: "Medium",
        5: "Low"
    }
    return mapping.get(priority_num, "Unknown")


def status_mapping(status):
    return {
        "Gesloten": "Closed",
        "Open": "Open"
    }.get(status, "Unknown")

def run_dgraph_query(query): # Fucntion to run a query on Dgraph 
    headers = {'Content-Type': 'application/graphql+-'}
    response = requests.post(f"{dgraph_url}/query", data=query, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"Query failed with status {response.status_code}: {response.text}")
        return None
 
def is_record_changed(record):
    issue_number_str = str(record['Code']) 
    query = f"""{{ 
        Ticket(func: eq(Ticket.issue_number, "{issue_number_str}")) {{
            uid
            Ticket.issue_description
            Ticket.priority 
            Ticket.ticket_status  
        }}
    }}""" 
    res = run_dgraph_query(query)
    print("Dgraph response:", res)

    # Check als het record nieuw is (niet bestaat in Dgraph)
    existing_ticket_uid = None 
    if not res or 'Ticket' not in res['data'] or len(res['data']['Ticket']) == 0:
        print(f"Record {record['Code']} is nieuw.") 
        return True, None  # Het record is nieuw
    
    else: 
        existing_ticket = res['data']['Ticket'][0]
        existing_ticket_uid = existing_ticket.get('uid')

        existing_priority = existing_ticket.get('Ticket.priority', 'Unknown')
        new_priority = priority_mapping(int(record['Prioriteit']))

        if ('Ticket.issue_description' in existing_ticket and existing_ticket['Ticket.issue_description'] != record['Omschrijving']) or \
        (existing_priority != new_priority) or \
        ('Ticket.ticket_status' in existing_ticket and existing_ticket['Ticket.ticket_status'] != status_mapping(record['Voortgangsstatus'])):
            print(f"Record {record['Code']} is gewijzigd.") 
            return True, existing_ticket_uid  # Het record is gewijzigd

    return (False, existing_ticket_uid)  # Het record is ongewijzigd


def delivery_report(err, msg):
    if err is not None:
        logging.error('Message delivery failed: {}'.format(err))
    else:
        logging.info('Message delivered to {} [{}]'.format(msg.topic(), msg.partition()))

def fetch_api_data():
    print("Fetching API data...")
    response = requests.get(api_url)
    if response.status_code == 200:
        print("API data fetched successfully.")
        return response.json()
    else:
        print("Error fetching data: Status code", response.status_code)
        return None

def send_to_kafka(data, existing_uid=None): # Function to send data to Kafka
    try:
        if data: 
            logging.info(f"Preparing to send record with Code: {data.get('Code')}")
            if existing_uid:
                data['existing_uid'] = existing_uid 
                logging.info(f"Existing UID {existing_uid} found for record with Code: {data.get('Code')}. Preparing to update the existing record.")
            serialized_data = json.dumps(data).encode('utf-8')  # Serialize the data to a JSON string
            producer.produce(kafka_topic, value=serialized_data, callback=delivery_report)
            producer.poll(0)
            logging.info(f"Data for record with Code: {data.get('Code')} successfully sent to Kafka topic: {kafka_topic}")
    except KafkaError as ke: 
        logging.error(f"Kafka error sending data to Kafka topic: {kafka_topic}. Error: {ke}")
    except Exception as e:
        logging.error(f"Failed to send data to Kafka topic: {kafka_topic}. Error: {e}")
        logging.debug("Data attempted to send:", data)

def process_and_send_records():
    data = fetch_api_data()
    if data:
        for record in data:
            is_changed, existing_uid = is_record_changed(record)
            if is_changed:
                send_to_kafka(record, existing_uid)
            else :
                logging.info(f"Record {record['Code']} is unchanged. Skipping...")
    else:
        print("No data received from API.")

    producer.flush()  # Wait for all messages to be delivered

def main():
    while True:
        process_and_send_records()
        print("Sleeping for 20 seconds...")
        sleep(20)  # Sleep for 20 seconds before fetching data again

if __name__ == "__main__":
    print("Starting Kafka Producer...")
    main()
