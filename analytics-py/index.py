import json
import numpy as np

def lambda_handler(event, context):
    temp = event.get('temp')
    humidity = event.get('humidity')
    flame = event.get('flame')
    air_quality = event.get('airQuality')
    array1 = np.array([1, 2, 3, 4, 5]);
    array2 = np.array([5, 4, 3, 2, 1]);
    coef = np.corrcoef(array1, array2)
    return {
        'statusCode': 200,
        'body': json.dumps({
            'probability': 0.5,
            'temp': temp,
            'humidity': humidity,
            'flame': flame,
            'airQuality': air_quality,
            'coef': [
                coef[0][1], coef[1][0],
            ],
        })
    }