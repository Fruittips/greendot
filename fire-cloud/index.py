import os
from dotenv import load_dotenv
import json
import asyncio
from datetime import datetime
from awsiot import mqtt5_client_builder, mqtt_connection_builder
from awscrt import mqtt5, http, auth
from supabase import create_client, Client
import numpy as np

load_dotenv() #load variables from .env

# Load environment variables
MQTT_HOST = os.getenv("MQTT_HOST")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

# MQTT Settings
ENDPOINT = os.getenv("MQTT_HOST");
REGION = "ap-southeast-1";
CLIENT_ID = "FIRE-CLOUD";
SENSOR_DATA_TOPIC = "greendot/sensor/data";
FLAME_PRESENCE_TOPIC = "greendot/status"

if not (SUPABASE_URL and SUPABASE_API_KEY):
    print("Missing SUPABASE_URL or SUPABASE_API_KEY environment variable")
    exit(1)

if not MQTT_HOST:
    print("Missing MQTT_HOST environment variable")
    exit(1)

if not (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY):
    print("Missing AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY environment variable")
    exit(1)

# Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

class MqttClient:
    def __init__(self):
        self.client = self._build_client()
        self.connection = self._establish_connection()
        
    def _build_client(self):
        client = mqtt5_client_builder.websockets_with_default_aws_signing(
            endpoint = ENDPOINT,
            region  = REGION,
            credentials_provider=auth.AwsCredentialsProvider.new_default_chain()
        )
        return client
    
    def _establish_connection(self):
        print("Connecting to AWS IoT Core...")
        connection = self.client.new_connection()
        print("Connected to AWS IoT Core!")
        self.client.start()
        return connection
    
    def subscribe(self):
        try:
            print("Subscribing to topic '{}'...".format(SENSOR_DATA_TOPIC))
            self.connection.subscribe(
                SENSOR_DATA_TOPIC,
                mqtt5.QoS.AT_LEAST_ONCE,
                self.listen_messages
            )
            print("[SUCCESS] subscribed to topic '{}'".format(SENSOR_DATA_TOPIC))
        except Exception as e:
            print(f"Error subscribing to topic: {e}")

    def listen_messages(self, topic, payload):
        payload = payload.decode()
        message_json = json.loads(payload)
        print(f"Message received on {topic}: {message_json}")

        temp = message_json["temp"]
        humidity = message_json["humidity"]
        air_quality_ppm = message_json["air"]
        flame_presence = message_json["flame"]
        
        r_value = get_r_value(temp, humidity)
        fire_probability = get_fire_probability(temp, humidity, air_quality_ppm, flame_presence, r_value)
        
        # update table in supabase
        try:
            supabase.table('firecloud') \
                .insert({
                    "node_id": message_json["id"],
                    "timestamp": convert_epoch_to_utc(message_json["timestamp"]),
                    "temperature": temp,
                    "humidity": humidity,
                    "air_quality_ppm": air_quality_ppm,
                    "flame_sensor_value": flame_presence,
                    "fire_probability": fire_probability, #TODO: insert the probability here (create a col on supabase first)
                    "r_value": r_value, #TODO: insert the r_value here//TODO: insert the r_value here as well (create in supabase first)
                }) \
                .execute()
        except Exception as e:
            print(f"Error inserting to supabase: {e}")
            
        print(f"Inserted into supabase table: 'firecloud'")
        
        #TODO: after inserting, publish to update flame probability on mqtt
        self.publish_fire_message(fire_probability)
    
    # publish fire status, 0 => no fire, 1 => fire
    def publish_fire_message(self, fire_probability):
        fire_probability_threshold = 0.3
        status = 0
        
        if (fire_probability >= fire_probability_threshold):
            status = 1
        
        try:
            print(f"Publishing fire status: {status}")
            self.connection.publish(FLAME_PRESENCE_TOPIC, 
                                json.dumps({"status": status}), 
                                mqtt5.QoS.AT_LEAST_ONCE)
            print(f"Published fire status: {status}")
        except Exception as e:
            print(f"Error publishing fire status: {e}")

def convert_epoch_to_utc(epoch_time):
    date = datetime.utcfromtimestamp(epoch_time)
    return date.isoformat()
        
#---------------------------------------------
# CALCULATION FOR FIRE PROBABILITY
def get_fire_probability (temp, humidity, air_quality, flame_presence, r_value):
    p_flame = flame_presence
    p_air = None
    p_temp = get_temp_proability(temp)
    p_temp_hum = get_temp_humidity_probability(r_value)
    
    
    p_fire = 0.3 * p_flame + 0.3 * p_air + 0.2 * p_temp_hum + 0.2 * p_temp
    return p_fire #TODO: replace w real values

#TODO: get the time for how long this air quality has been all
def get_air_quality_probability(air_quality):
    #TODO: time is 5 minutes
    air_quality_threshold = 100 # TODO: get the threshold value
    if (air_quality > air_quality_threshold):
        return 1
    else:
        return 0

def get_temp_proability(temp):
    temp_threshold = 40 # highest in sg: 37 + 3 = 40 deg (3 for threshold)
    if (temp > temp_threshold):
        return 1
    else:
        return 0
    
def get_temp_humidity_probability(r_value):
    r_value_threshold = 0.5 # TODO: get the threshold value
    if (r_value > r_value_threshold):
        return 1
    else:
        return 0

def get_r_value(temp, humidity): #TODO: get the r_value
    return None

#---------------------------------------------

async def main():
    mqtt_client = MqttClient()
    mqtt_client.subscribe() # subscribe to topic

    while True:
        await asyncio.sleep(1)  # Keep the script running


asyncio.run(main())