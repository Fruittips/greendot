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
SUPABASE_TABLE_NAME = "firecloud"

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

# GLOBAL VARIABLES
PAST_RECORDS_DURATION = 5 # in minutes
aq_duration = None # duration of air quality raising above threshold
fire_status = 0 # 0 => no fire, 1 => fire
no_fire_duration = None # duration of fire

#TODO: check if date time library is correct not
#TODO: check if UTC time is accurate
#TODO: calc r value from past records
class MqttClient:
    def __init__(self):
        self.supabase = self._create_supabase_client()
        self.client = self._build_client()
        self.connection = self._establish_connection()
        
    # Supabase client
    def _create_supabase_client(self):
        supabase = create_client(SUPABASE_URL, SUPABASE_API_KEY)
        return supabase
        
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
        
        # get past records from supabase
        temp_hum_data = []
        try:
            temp_hum_data = self.supabase.rpc("get_past_records", {"interval_string": f"{PAST_RECORDS_DURATION} minutes", })
        except Exception as e:
            print(f"Error getting past records supabase: {e}")

        r_value = get_r_value(temp_hum_data)
        fire_probability = get_fire_probability(temp, humidity, air_quality_ppm, flame_presence, r_value)
        
        # update table in supabase
        try:
            self.supabase.table(SUPABASE_TABLE_NAME) \
                .insert({
                    "node_id": message_json["id"],
                    "timestamp": convert_epoch_to_utc(message_json["timestamp"]),
                    "temperature": temp,
                    "humidity": humidity,
                    "air_quality_ppm": air_quality_ppm,
                    "flame_sensor_value": flame_presence,
                    "fire_probability": fire_probability,
                    "r_value": r_value,
                }) \
                .execute()
        except Exception as e:
            print(f"Error inserting to supabase: {e}")
            
        print(f"Inserted into supabase table: '{SUPABASE_TABLE_NAME}'")
        
        self.validate_and_publish_fire_message(fire_probability)
        
        
    
    # publish fire status, 0 => no fire, 1 => fire
    def validate_and_publish_fire_message(self, fire_probability):
        fire_probability_threshold = 0.3
        
        if (fire_probability >= fire_probability_threshold):
            if (fire_status == 0):
                self.publish_fire_message(1)
            fire_status = 1
        
        #fire could be dying off
        if (fire_status == 1 and fire_probability < fire_probability_threshold):
            if (no_fire_duration is None):
                no_fire_duration = datetime.now()
            else:
                time_diff = datetime.now() - no_fire_duration
                if (time_diff.minute > 5):
                    self.publish_fire_message(0)
                    fire_status = 0
                    no_fire_duration = None

    def _publish_fire_message(self,fire_status):
        try:
            print(f"Publishing fire status: {fire_status}")
            self.connection.publish(FLAME_PRESENCE_TOPIC, 
                                json.dumps({"status": fire_status}), 
                                mqtt5.QoS.AT_LEAST_ONCE)
            print(f"Published fire status: {fire_status}")
        except Exception as e:
            print(f"Error publishing fire status: {e}")

def convert_epoch_to_utc(epoch_time):
    date = datetime.utcfromtimestamp(epoch_time)
    return date.isoformat()
        
#---------------------------------------------
# CALCULATION FOR FIRE PROBABILITY
def get_fire_probability (temp, humidity, air_quality, flame_presence, r_value):
    p_flame = flame_presence
    p_air = get_air_quality_probability(air_quality)
    p_temp = get_temp_proability(temp)
    p_temp_hum = get_temp_humidity_probability(r_value)
    
    p_fire = 0.3 * p_flame + 0.3 * p_air + 0.2 * p_temp_hum + 0.2 * p_temp
    return p_fire

def get_air_quality_probability(air_quality):
    air_quality_threshold = 500 # value fluctuates between 500 - 550 depending on environment
    
    if (air_quality > air_quality_threshold):
        if (aq_duration == None):
            aq_duration = datetime.now()
            return 0
        else:
            time_diff = datetime.now() - aq_duration
            if (time_diff.minute > 5): # if air quality has been above threshold for 5 mins
                return 1
            else:
                return 0
    else:
        aq_duration = None # reset aq_duration
        return 0

def get_temp_proability(temp):
    temp_threshold = 40 # highest in sg: 37 + 3 = 40 deg (3 for threshold)
    if (temp > temp_threshold):
        return 1
    else:
        return 0
    
def get_temp_humidity_probability(r_value):
    r_reference = -0.62
    
    r_ratio = r_value / r_reference
    
    if (r_ratio > 1):
        return 1
    elif (r_ratio < 0):
        return 0
    else:
        return r_ratio

def get_r_value(temp_hum_records): 
    #TODO: calculate r value from records of temp and hum
    return None

#---------------------------------------------

async def main():
    mqtt_client = MqttClient()
    mqtt_client.subscribe() # subscribe to topic

    while True:
        await asyncio.sleep(1)  # Keep the script running


asyncio.run(main())