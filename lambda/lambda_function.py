import json
# from dotenv import load_dotenv
import numpy as np
import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
PAST_RECORDS_DURATION = 120 # in minutes

def lambda_handler(event, context):
    rowId = event.get('rowId')
    temp = event.get('temp')
    flame = event.get('flame')
    
    # get past records from supabase
    temp_hum_aq_res = None
    try:
        temp_hum_aq_res = supabase.rpc("get_past_records", {"interval_string": f"{PAST_RECORDS_DURATION} minutes", }).execute()
    except Exception as e:
        print(f"Error getting past records supabase: {e}")
        
    if (temp_hum_aq_res == None or not temp_hum_aq_res.data):
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Error getting past records from supabase'
            })
        }
        
    temp_hum_aq_data = temp_hum_aq_res.data
    temp_arr = [] if temp_hum_aq_data.get("all_temperature", None) is None else temp_hum_aq_data.get("all_temperature")
    humidity_arr = [] if temp_hum_aq_data.get("all_humidity", None) is None else temp_hum_aq_data.get("all_humidity")
    aq_arr = [] if temp_hum_aq_data.get("all_air_quality_ppm", None) is None else temp_hum_aq_data.get("all_air_quality_ppm")
        
    r_value = get_r_value(temp_arr, humidity_arr)
    fire_probability = get_fire_probability(temp, aq_arr, flame, r_value)
    
    #update row in supabase table with r_value and fire_probability
    try:
        data, count = supabase.table('firecloud') \
                                .update({
                                    "r_value": r_value,
                                    "fire_probability": fire_probability,
                                    }) \
                                .eq('id', rowId) \
                                .execute()
    except Exception as e:
        print(f"Error updating row in supabase: {e}")

    return json.dumps({
        'statusCode': 200,
        'body': json.dumps({
            'fire_probability': fire_probability,
            'r_value': r_value,
        })
    })
    
def get_fire_probability (temp, aq_arr , flame_presence, r_value):
    p_flame = flame_presence
    p_air = get_air_quality_probability(aq_arr)
    p_temp = get_temp_proability(temp)
    p_temp_hum = get_temp_humidity_probability(r_value)
    
    p_fire = 0.3 * p_flame + 0.3 * p_air + 0.2 * p_temp_hum + 0.2 * p_temp
    return p_fire

def get_air_quality_probability(air_quality_arr):
    air_quality_threshold = 500 # value fluctuates between 500 - 550 depending on environment
    
    if (len(air_quality_arr) == 0):
        return 0
    
    # if every value in the array is above threshold, return 1
    if (all(air_quality > air_quality_threshold for air_quality in air_quality_arr)):
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
    r_reference = -0.62
    
    r_ratio = r_value / r_reference
    
    if (r_ratio > 1):
        return 1
    elif (r_ratio < 0):
        return 0
    else:
        return r_ratio

def get_r_value(temp_arr, humidity_arr): 
    r_corrcoef = np.corrcoef(temp_arr, humidity_arr, rowvar=False)
    r_actual = r_corrcoef[0][1]
    return r_actual

# #TODO: DONT PUSH THIS REMOVE IT BEFORE PUSHING
# if __name__ == "__main__":
#    lambda_handler({
#        "rowId":646,
#        "temp":30.9,
#        "humidity": 72.4,
#        "flame": 0,
#        "airQuality": 526.858
#        }, None)