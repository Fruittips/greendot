import json
# from dotenv import load_dotenv
import numpy as np
import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def lambda_handler(event, context):
    nodeId = event.get('nodeId')
    rowId = event.get('rowId')
    temp = event.get('temp')
    flame = event.get('flame')
    utc_datatime = event.get('utc_datetime_string')
    
    # get past records from supabase
    temp_hum_aq_res = None
    try:
        temp_hum_aq_res = supabase.rpc("get_past_records", {
            "node_id":  nodeId, 
            "utc_datetime_string": utc_datatime}).execute()
    except Exception as e:
        print(f"Error getting past records supabase: {e}")
        
    if (temp_hum_aq_res == None or temp_hum_aq_res.data == None):
        return json.dumps({
            'statusCode': 500,
            'body': {
                'error': 'Error getting past records from supabase'
            }
        })
        
    temp_hum_aq_data = temp_hum_aq_res.data
    temp_arr = [] if temp_hum_aq_data.get("all_temperature", None) is None else temp_hum_aq_data.get("all_temperature")
    humidity_arr = [] if temp_hum_aq_data.get("all_humidity", None) is None else temp_hum_aq_data.get("all_humidity")
    aq_arr = [] if temp_hum_aq_data.get("all_air_quality_ppm", None) is None else temp_hum_aq_data.get("all_air_quality_ppm")
    
    r_value = 0
    fire_probability = 0
    
    if len(temp_arr) >= 25 and len(humidity_arr) >= 25:
        r_value = get_r_value(temp_arr, humidity_arr)
    
    # if less than 25 records, dont calculate r value and return default fire probability
    else:
        try:
            supabase.table('firecloud') \
                        .update({
                            "r_value": r_value,
                            "fire_probability": fire_probability,
                            }) \
                        .eq('id', rowId) \
                        .execute()
        except Exception as e:
            print(f"Error updating row in supabase: {e}")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                'fire_probability': fire_probability,
                'r_value': r_value,
            })
        }

    fire_probability = get_fire_probability(temp, aq_arr, flame, r_value)
    
    try:
        supabase.table('firecloud') \
                    .update({
                        "r_value": r_value,
                        "fire_probability": fire_probability,
                        }) \
                    .eq('id', rowId) \
                    .execute()
    except Exception as e:
        print(f"Error updating row in supabase: {e}")
    
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            'fire_probability': fire_probability,
            'r_value': r_value,
        })
    }
    
def get_fire_probability (temp, aq_arr , flame_presence, r_value):
    p_flame = flame_presence
    p_air = get_air_quality_probability(aq_arr)
    p_temp = get_temp_probability(temp)
    p_temp_hum = get_temp_humidity_probability(r_value)
    
    p_fire = 0.3 * p_flame + 0.3 * p_air + 0.2 * p_temp_hum + 0.2 * p_temp
    return p_fire

def get_air_quality_probability(air_quality_arr):
    air_quality_threshold = 450
    
    if (len(air_quality_arr) == 0):
        return 0
    
    # check if at least 10 hits above threshold
    hits_above_threshold = 0
    for air_quality in air_quality_arr:
        if (air_quality > air_quality_threshold):
            hits_above_threshold += 1
        if (hits_above_threshold >= 10):
            return 1
    return 0

def get_temp_probability(temp):
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

def get_r_value(temp_arr, humidity_arr): 
    if np.std(temp_arr) == 0 or np.std(humidity_arr) == 0:
        return 0
    
    r_corrcoef = np.corrcoef(temp_arr, humidity_arr, rowvar=False)
    r_actual = r_corrcoef[0][1]
    return r_actual