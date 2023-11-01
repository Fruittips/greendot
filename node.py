import machine
import network
import bluetooth
import umqtt.simple
import time
import uasyncio as asyncio
import aioble
import struct
import json

# WIFI
WIFI_SSID = "skku"
WIFI_PASS = "skku1398"

# MQTT
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"
_SENSOR_DATA_TOPIC = "greendot/sensor/data"

# BLE
_GREENDOT_SERVICE_UUID = bluetooth.UUID(0x181A)
_DATA_UUID = bluetooth.UUID(0x2A6A)
_FLAME_SENSOR_UUID = bluetooth.UUID(0x2A6A)
_TEMP_SENSOR_UUID = bluetooth.UUID(0x2A6B)
_AIR_SENSOR_UUID = bluetooth.UUID(0x2A6C)
_ADV_INTERVAL_MS = 250_000

# Shared
_DEVICE_NAME_PREFIX = "GREENDOT-"
_DEVICE_HIERARCHY = 1
_NODE_ID = 1
_DEVICE_NAME = _DEVICE_NAME_PREFIX + _DEVICE_HIERARCHY + "-" + "NODE-" + _NODE_ID
_DEVICE_MODE = "CENTRAL"


class BleCentralManager:
    def __init__(self, mqtt_client):
        self.devices = {}
        self.mqtt_client = mqtt_client
        self.MAX_RECONNECT_ATTEMPTS = 3
    
    async def run(self):
        # Scan for 5 seconds, in active mode, with very low interval/window (to
        # maximise detection rate).
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                # See if it matches our name and the environmental sensing service.
                name = result.name()
                services = result.services()
                if name is not None and services is not None and _DEVICE_NAME_PREFIX in name and _GREENDOT_SERVICE_UUID in services:
                    hierachy = name.split("-")[1]
                    if hierachy == _DEVICE_HIERARCHY+1:
                        device = result.device
                        await self.__connect_to_device(device, name)
                        asyncio.create_task(self.__listen_to_device_characteristic(name))

    async def __connect_to_device(self, device, name):
        connection = await device.connect()
        greendot_service = await connection.service(_GREENDOT_SERVICE_UUID)
        data_characteristic = await greendot_service.characteristic(_DATA_UUID)
        # Subscribe for notifications
        await data_characteristic.subscribe(notify=True)
        self.devices[name] = {
            'device': device,
            'connection': connection,
            'data_characteristic': data_characteristic
        }

    async def __listen_to_device_characteristic(self, name):
        device_data = self.devices[name]
        
        while True:
            try:
                data = await device_data['data_characteristic'].notified()

                print(f"Device: {name}, Temp: {self.__decode_json_data(data)}")
                self.mqtt_client.send_sensor_data(data)
            
            except aioble.GattError:  
                print(f"Device {name} disconnected.")
                isReconnected = await self.__attempt_reconnect(device_data['device'])
                if not isReconnected:
                    del self.devices[name]
                    await self.scan_and_connect()
                    return
                print(f"Device {name} reconnected.")
            
    async def __attempt_reconnect(self, device):
        for _ in range(self.MAX_RECONNECT_ATTEMPTS):
            try:
                print(f"Attempting to reconnect to {device}")
                await self.__connect_to_device(device)
                return True
            except Exception as e:
                print(f"Reconnect attempt failed due to {e}")
                await asyncio.sleep(1)
        return False

    def __decode_json_data(self, data):
        return json.loads(data.decode('utf-8'))
    
    def __encode_json_data(self, data):
        return json.dumps(data).encode('utf-8')
    
class BlePeripheralManager:
    def __init__(self):
        self.start_sending_event = asyncio.Event()
        self.connection_to_send_to = None
        self.devices_to_aggregate = {}
        self.sampling_interval = 5
        self.greendot_service = aioble.Service(_GREENDOT_SERVICE_UUID)
        self.data_characteristic = aioble.Characteristic(self.greendot_service, _DATA_UUID, read=True, notify=True)
        aioble.register_services(self.greendot_service)
        aioble.core.ble.gatts_set_buffer(self._rx_characteristic._value_handle, 128)

    async def run(self):
        asyncio.create_task(self.__advertise())
        asyncio.create_task(self.__notify_sensor_data())
        asyncio.create_task(self.__scan_and_connect())

    async def __advertise(self):
        connection = await aioble.advertise(
            _ADV_INTERVAL_MS,
            name=_DEVICE_NAME,
            services=[_GREENDOT_SERVICE_UUID],
        )
        print("Connection from", connection.device)
        self.connection_to_send_to = connection
        self.start_sending_event.set()
        await connection.disconnected()
        self.start_sending_event.clear()
        print("Disconnected. Restarting advertisement...")

    async def __notify_sensor_data(self):
        while True:
            await self.start_sending_event.wait()
            while self.start_sending_event.is_set():
                # TODO: Get sensor data
                temp_sensor_data = 1
                flame_sensor_data = 2
                air_sensor_data = 3

                self.__notify(
                    self.__encode_json_data({
                        "id": _NODE_ID,
                        "temp": temp_sensor_data,
                        "flame": flame_sensor_data,
                        "air": air_sensor_data
                    })
                )

    async def __notify(self, data):
        self.data_characteristic.write(data)
        self.data_characteristic.notify(self.connection_to_send_to)
        await asyncio.sleep(self.sampling_interval)

    async def __scan_and_connect(self):
        # Scan for 5 seconds, in active mode, with very low interval/window (to
        # maximise detection rate).
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                # See if it matches our name and the environmental sensing service.
                name = result.name()
                services = result.services()
                if name is not None and services is not None and _DEVICE_NAME_PREFIX in name and _GREENDOT_SERVICE_UUID in services:
                    x = name.split("-")
                    hierachy = x[1]
                    id = x[-1]
                    if hierachy == _DEVICE_HIERARCHY+1:
                        device = result.device
                        await self.__connect_to_device(device, name, id)
                        asyncio.create_task(self.__listen_to_device_characteristic(name))

    async def __connect_to_device(self, device, name, id):
        connection = await device.connect()
        greendot_service = await connection.service(_GREENDOT_SERVICE_UUID)
        data_characteristic = await greendot_service.characteristic(_DATA_UUID)
        # Subscribe for notifications
        await data_characteristic.subscribe(notify=True)
        self.devices_to_aggregate[name] = {
            'id': id,
            'device': device,
            'connection': connection,
            'data_characteristic': data_characteristic
        }

    async def __listen_to_device_characteristic(self, name):
        device_data = self.devices_to_aggregate[name]
        
        while True:
            try:
                data = await device_data['data_characteristic'].notified()
                print(f"Device: {name}, Temp: {self.__decode_json_data(data)}")
                
                self.__notify(
                    data
                )
            except aioble.GattError:
                print(f"Device {name} disconnected.")
                isReconnected = await self.__attempt_reconnect(device_data['device'])
                if not isReconnected:
                    del self.devices_to_aggregate[name]
                    await self.scan_and_connect()
                    return
                print(f"Device {name} reconnected.")
            
    async def __attempt_reconnect(self, device):
        for _ in range(self.MAX_RECONNECT_ATTEMPTS):
            try:
                print(f"Attempting to reconnect to {device}")
                await self.__connect_to_device(device)
                return True
            except Exception as e:
                print(f"Reconnect attempt failed due to {e}")
                await asyncio.sleep(1)
        return False

    def __decode_json_data(self, data):
        return json.loads(data.decode('utf-8'))
    
    def __encode_json_data(self, data):
        return json.dumps(data).encode('utf-8')
    

class MqttClient:
    def __init__(self):
        self.client_id = _DEVICE_NAME
        self.__connect_mqtt()

    def send_sensor_data(self, data):
        self.__publish(
            _SENSOR_DATA_TOPIC,
            data
        )

    def __connect_mqtt(self):
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
            self.mqtt_client.connect()
            print("connected to mqtt broker")
        except:
            print("error connecting to mqtt broker")

    def __publish(self, topic, data):
        data = self.__encode_data(data)
        self.mqtt_client.publish(topic, data)

    def __encode_data(self, data):
        return json.dumps(data)
    
    def __decode_data(self, data):
        return json.loads(data)
    

class Node:
    def __init__(self):
        self._connect_wifi()
        self.mqtt_client = MqttClient()
        self.bt_node = BleCentralManager(self.mqtt_client) if _DEVICE_MODE == "CENTRAL" else BlePeripheralManager()

    def _connect_wifi(self):
        self.wifi = network.WLAN(network.STA_IF)
        self.wifi.active(True)
        self.wifi.connect(WIFI_SSID, WIFI_PASS)
        while not self.wifi.isconnected():
            print("connecting to Wifi...")
            time.sleep(2)
        print("Wifi connected", self.wifi.isconnected())
    
    async def start(self):
        print("starting")
        await asyncio.gather(
            self.bt_node.run(),
        )
                

print("Hello world")
node = Node()
asyncio.run(node.start())

print("Hello world")
node = Node()
asyncio.run(node.start())
