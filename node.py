import machine
import network
import bluetooth
import ustruct
import umqtt.simple
import time
import ubinascii
import uos
from micropython import const
import uasyncio as asyncio
import aioble

import random
import struct
import json

WIFI_SSID = "skku"
WIFI_PASS = "skku1398"
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"


_GREENDOT_SERVICE_UUID = bluetooth.UUID(0x181A)

_FLAME_SENSOR_UUID = bluetooth.UUID(0x2A6A)
_TEMP_SENSOR_UUID = bluetooth.UUID(0x2A6B)
_AIR_SENSOR_UUID = bluetooth.UUID(0x2A6C)

_ADV_INTERVAL_MS = 250_000
_READ_INTERVAL_MS = 2000
_CENTRAL_SCAN_TIMEOUT = 3000

_DEVICE_NAME_PREFIX = "GREENDOT-"
_DEVICE_NAME = _DEVICE_NAME_PREFIX + "NODE-1"

_STATUS_TOPIC = "greendot/node/status"

current_mode = "default"

class BTClient:
    def __init__(self, mqtt_client):
        self.connected_device_name = None
        self.device = None
        self.connection = None
        self.temp_characteristic = None
        self.flame_characteristic = None
        self.air_characteristic = None
        self.mqtt_client = mqtt_client
        
    async def act_as_central(self):
        try:
            # try to scan and connect for 5 minutes
            await asyncio.wait_for(self.__scan_for_nodes(), timeout=_CENTRAL_SCAN_TIMEOUT)
            print("Found device, connecting...")
            await self.__connect_to_node()
            print("Connected, receiving data...")
            return True
        except asyncio.TimeoutError:
            print("Timeout while trying to scan or connect.")
            return False
    
    async def set_peripheral_service(self):
        greendot_service = aioble.Service(_GREENDOT_SERVICE_UUID)
        self.temp_characteristic = aioble.Characteristic(greendot_service, _TEMP_SENSOR_UUID, read=True, notify=True)
        self.flame_characteristic = aioble.Characteristic(greendot_service, _FLAME_SENSOR_UUID, read=True, notify=True)
        self.air_characteristic = aioble.Characteristic(greendot_service, _AIR_SENSOR_UUID, read=True, notify=True)
        aioble.register_services(greendot_service)
    
    async def __scan_for_nodes(self):
        # Scan for 5 seconds, in active mode, with very low interval/window (to
        # maximise detection rate).
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                # See if it matches our name and the environmental sensing service.
                name = result.name()
                services = result.services()
                if name is not None and services is not None and _DEVICE_NAME_PREFIX in name and _GREENDOT_SERVICE_UUID in services:
                    self.connected_device_name = name
                    self.device = result.device
        return None
    
    async def __connect_to_node(self):
        if self.device is None:
            print("No device found")
            return
        try:
            connection = await self.device.connect()
            self.connection = connection
            greendot_service = await self.connection.service(_GREENDOT_SERVICE_UUID)
            self.temp_characteristic = await greendot_service.characteristic(_TEMP_SENSOR_UUID)
            self.flame_characteristic = await greendot_service.characteristic(_FLAME_SENSOR_UUID)
            self.air_characteristic = await greendot_service.characteristic(_AIR_SENSOR_UUID)
        except asyncio.TimeoutError:
            print("Timeout during connection")
            return
        
    async def recieve_and_publish_loop(self):
        global current_mode
        while current_mode == "central":
            if self.connection is None:
                print("Connection failed")
                return
            if self.air_characteristic is None:
                print("Air characteristic not found")
                return
            if self.temp_characteristic is None:
                print("Temp characteristic not found")
                return
            if self.flame_characteristic is None:
                print("Flame characteristic not found")
                return
            temp = self.__decode_data(await self.temp_characteristic.read())
            flame = self.__decode_data(await self.flame_characteristic.read())
            air = self.__decode_data(await self.air_characteristic.read())
            print("Temp: ", str(temp), "Flame: ", str(flame), "Air: ", str(air))
            self.mqtt_client.send_sensor_data(self.connected_device_name ,temp, flame, air)
            await asyncio.sleep_ms(_READ_INTERVAL_MS)
    
    async def advertise(self):
        global current_mode
        while current_mode == "peripheral":
            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=_DEVICE_NAME,
                services=[_GREENDOT_SERVICE_UUID],
            ) as connection:
                print("Connection from", connection.device)
                await connection.disconnected()
                print("Disconnected. Restarting advertisement...")

    async def send_sensor_data(self):
        global current_mode
        while current_mode == "peripheral":
            temp_sensor_data = 1
            flame_sensor_data = 2
            air_sensor_data = 3
            
            temp_sensor_data = self.__encode_data(temp_sensor_data)
            flame_sensor_data = self.__encode_data(flame_sensor_data)
            air_sensor_data = self.__encode_data(air_sensor_data)
            
            self.temp_characteristic.write(temp_sensor_data)
            self.flame_characteristic.write(flame_sensor_data)
            self.air_characteristic.write(air_sensor_data)
            await asyncio.sleep_ms(1000)

    def __encode_data(self, data):
        return struct.pack("<h", int(data))
    
    def __decode_data(self, data):
        return struct.unpack("<h", data)[0]
    
class MqttClient:
    def __init__(self):
        self.client_id = _DEVICE_NAME
        self.dead_nodes_queue = []
        self._connect_mqtt()

    def send_sensor_data(self, nodeId, temp, flame, air):
        self._publish(
            'greendot/sensor/data',
            {
                'nodeId': nodeId,
                'temp': temp,
                'flame': flame,
                'air': air
            }
        )

    def _on_message(self, topic, message):
        data = self._decode_data(message)
        print('Received message on topic {}: {}'.format(topic, data))
        if topic == _STATUS_TOPIC and 'node_id' in data and 'status' in data:
            node_id = data['node_id']
            self.dead_nodes_queue.append(node_id)
    
    def pop_dead_node(self):
        if self.dead_nodes_queue:
            return self.dead_nodes_queue.pop(0)
        return None

    def check_for_dead_node(self):
        if self.dead_nodes_queue and len(self.dead_nodes_queue) > 0:
            return self.dead_nodes_queue[0]
        return None

    def _connect_mqtt(self):
        with open("device.crt", 'r') as f:
            DEVICE_CERT = f.read()
        with open("private.key", 'r') as f:
            PRIVATE_KEY = f.read()
        ssl_params = {"key":PRIVATE_KEY, "cert":DEVICE_CERT, "server_side":False}
        try:
            self.mqtt_client = umqtt.simple.MQTTClient(
                client_id=self.client_id,
                server= MQTT_BROKER_ENDPOINT,
                port=8883,
                keepalive=1500, 
                ssl=True,
                ssl_params=ssl_params
            )
            self.mqtt_client.set_callback(self._on_message)
            self.mqtt_client.will_set(_STATUS_TOPIC, "offline", retain=True)
            self.mqtt_client.connect()
            self.mqtt_client.subscribe('greendot/node/status')
            print("connected to mqtt broker")
        except:
            print("error connecting to mqtt broker")

    def _publish(self, topic, data):
        data = self._encode_data(data)
        self.mqtt_client.publish(topic, data)

    def _encode_data(self, data):
        return json.dumps(data)
    
    def _decode_data(self, data):
        return json.loads(data)
    
class SensorManager:
    def __init__(self, mqtt_client):
        self.mqtt_client = mqtt_client

    async def read_publish_sensors_data(self):
        global current_mode
        while current_mode == "default" or current_mode == "central":
            temp_sensor_data = 1
            flame_sensor_data = 2
            air_sensor_data = 3
            
            self.mqtt_client.send_sensor_data(_DEVICE_NAME ,temp_sensor_data, flame_sensor_data, air_sensor_data)
            await asyncio.sleep_ms(_READ_INTERVAL_MS)

class Node:
    def __init__(self):
        self._connect_wifi()
        self.mqtt_client = MqttClient()
        self.bt_node = BTClient(self.mqtt_client)
        self.sensor_manager = SensorManager(self.mqtt_client)

    def _connect_wifi(self):
        self.wifi = network.WLAN(network.STA_IF)
        self.wifi.active(True)
        self.wifi.connect(WIFI_SSID, WIFI_PASS)
        while not self.wifi.isconnected():
            print("connecting to Wifi...")
            time.sleep(2)
        print("Wifi connected", self.wifi.isconnected())
        
    async def central_mode(self):
        global current_mode
        while True:
            if current_mode == "central":
                print("central mode")
                connection_successful = await self.bt_node.act_as_central()
                if connection_successful:
                    self.mqtt_client.pop_dead_node()
                    recieve_and_publish_BLE = asyncio.create_task(self.bt_node.recieve_and_publish_loop())
                    read_and_publish_LOCAL = asyncio.create_task(self.sensor_manager.read_publish_sensors_data())
                    await asyncio.gather(recieve_and_publish_BLE, read_and_publish_LOCAL)
                else:
                    print("BLE Connection failed, going back to default behavior")
                    self.mqtt_client.pop_dead_node()
                    current_mode = "default"

    async def peripheral_mode(self):
        global current_mode
        while True:
            if current_mode == "peripheral":
                print("peripheral mode")
                self.bt_node.set_peripheral_service()
                adv = asyncio.create_task(self.bt_node.advertise())
                send_data = asyncio.create_task(self.bt_node.send_sensor_data())
                await asyncio.gather(adv, send_data)
            await asyncio.sleep(2) 

    async def default_mode(self):
        global current_mode
        while True:
            if current_mode == "default":
                await self.sensor_manager.read_publish_sensors_data()
            await asyncio.sleep(2)


    async def check_and_switch_modes(self):
        global current_mode
        while True:
            if self.wifi.isconnected():
                dead_node_id = self.mqtt_client.check_for_dead_node()
                if dead_node_id is not None:
                    current_mode = "central"
                else:
                    current_mode = "default"
            else:
                current_mode = "peripheral"
            await asyncio.sleep(2)
    
    async def start(self):
        print("starting")
        await asyncio.gather(
            self.check_and_switch_modes(),
            self.central_mode(),
            self.peripheral_mode(),
            self.default_mode(),
        )
                

print("Hello world")
node = Node()
asyncio.run(node.start())
