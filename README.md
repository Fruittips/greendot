# Green·Dot
## Forest Fire Early Detection System
50.046 Cloud Computing and Internet of Things

Team 03: \
Brandon Ong (1004997) \
Mah Yi Da (1005024) \
Bryce Goh (1005016) \
Tan Lay Lin (1005474) 

## How to Run

### ESP32
1. `sensors/lib` \
Contains the necessary library code for the esp32 to work

2. `node.py` \
To be flashed as `main.py` in the ESP32, contains the main code to be executed when the ESP32 is booted

3. `sensors.py` \
This contains code for sampling of raw data for the sensors attached to the ESP32

### RPi
`rpi` folder contains the necessary files for connection to AWS IoT core MQTT broker as well. It also contains `rpi.py`, which is the code that is to be executed for upon startup of the system.

from the root directory `cd/rpi` and run:
```
pip install -r requirements.txt
bash run.sh
```

## File structure

### ```analytics-py```
Our analytics service runs on a serverless lambda function using python. 

### ```fire-cloud```
Contains the central server code that will run on Elastic Beanstalk (EBS). The central server runs on NodeJS and is subscribed to our MQTT broker. Upon receiving sensor data that was published to our MQTT broker, it directs it to both our database and lambda function.

### ```lambda```
Our analytics service runs on a serverless lambda function using python. It is responsible for calculating the probability of fire and updating it to our database.

### ```rpi```
Acts as the central node for our system. It establishes persistent Bluetooth Low Energy (BLE) connection with all ESP32 child nodes, gathers data and publishes it to the MQTT broker.

### ```sensors```
The `/lib` folder contains all necessary files needed to read data from the sensors used with micropython.

### ```node.py``` and ```sensors.py```
Used by the ESP32s to allow persistent Bluetooth Low Energy (BLE) connection with the central node (RPi), gather data from sensors and transmit data to the central node.