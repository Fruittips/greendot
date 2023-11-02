import machine
import network
import bluetooth
import umqtt.simple
import time
import uasyncio as asyncio
import aioble
import struct
import ujson as json
import gc
import mqtt_as as MQTTAS

# aioble.config(mtu=512)

# WIFI
# WIFI_SSID = "skku"
# WIFI_PASS = "skku1398"
# WIFI_SSID = "Pixel_myd"
# WIFI_PASS = "THEMAHYIDA"
WIFI_SSID = "beebblink"
WIFI_PASS = "wifi@GOHFAM3456X!"

# MQTT
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"
_SENSOR_DATA_TOPIC = b'greendot/sensor/data'

# BLE
_GREENDOT_SERVICE_UUID = bluetooth.UUID(0x181A)
_DATA_UUID = bluetooth.UUID(0x2A6A)
_FLAME_SENSOR_UUID = bluetooth.UUID(0x2A6A)
_TEMP_SENSOR_UUID = bluetooth.UUID(0x2A6B)
_AIR_SENSOR_UUID = bluetooth.UUID(0x2A6C)
_ADV_INTERVAL_MS = 250_000

# Shared
_DEVICE_NAME_PREFIX = "GREENDOT-"
_DEVICE_HIERARCHY = 0
_NODE_ID = 0
_DEVICE_NAME = _DEVICE_NAME_PREFIX + str(_DEVICE_HIERARCHY) + "-" + "NODE-" + str(_NODE_ID)
_DEVICE_MODE = "CENTRAL" if (_NODE_ID == 0 and _DEVICE_HIERARCHY == 0) else "PHERIPHERAL"



class BleCentralManager:
    def __init__(self, mqtt_client):
        self.device = None
        self.MAX_RECONNECT_ATTEMPTS = 3
        self.buffer = []
        self.mqtt_client = mqtt_client
        self.send_buffer_mode = asyncio.Event()
    
    async def run(self):
        self.send_buffer_mode.clear()
        await self.check_for_mode()

    async def check_for_mode(self):
        while True:
            if self.send_buffer_mode.is_set():
                await self.__send_to_mqtt()
            else:
                await self.scan_and_collect_data()
            await asyncio.sleep(2)

    async def scan_and_collect_data(self):
        # Scan for 5 seconds, in active mode, with very low interval/window (to
        # maximise detection rate).
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                # See if it matches our name and the environmental sensing service.
                name = result.name()
                services = result.services()
                if name is not None and services is not None and _DEVICE_NAME_PREFIX in name and _GREENDOT_SERVICE_UUID in services:
                    print(f"Scanned {name}")
                    hierachy = int(name.split("-")[1])
                    if hierachy == int(_DEVICE_HIERARCHY)+1:
                        print("Found device", name)
                        device = result.device
                        await self.__connect_to_device(device, name)
                        # await self.__listen_to_device_characteristic(name)
                        await self.recieve_and_publish_loop(name)
                        
                

    async def __connect_to_device(self, device, name):
        connection = await device.connect()
        # await connection.exchange_mtu(512)
        greendot_service = await connection.service(_GREENDOT_SERVICE_UUID)
        flame_characteristic = await greendot_service.characteristic(_FLAME_SENSOR_UUID)
        air_characteristic = await greendot_service.characteristic(_AIR_SENSOR_UUID)
        temp_characteristic = await greendot_service.characteristic(_TEMP_SENSOR_UUID)
        # Subscribe for notifications
        await flame_characteristic.subscribe(notify=True)
        await air_characteristic.subscribe(notify=True)
        await temp_characteristic.subscribe(notify=True)
        self.device = {
            'device': device,
            'connection': connection,
            'flame_characteristic': flame_characteristic,
            'air_characteristic': air_characteristic,
            'temp_characteristic': temp_characteristic,
        }

    async def __send_to_mqtt(self):
        while self.send_buffer_mode.is_set():
            print("disconnecting")
            await self.device['connection'].disconnect()
            print("disconnected")
            await asyncio.sleep(8)
            print("disconnected time over")
            while len(self.buffer) > 0:
                # disconnect_coroutines = [
                #     self.devices[name]['connection'].disconnect()
                #     for name in self.devices
                # ]
                # await asyncio.gather(*disconnect_coroutines)
                data = self.buffer.pop(0)
                self.mqtt_client.send_sensor_data(data)
                print("Sent to mqtt")
            self.send_buffer_mode.clear()
            
    async def recieve_and_publish_loop(self, name):
        device_data = self.device
        while not self.send_buffer_mode.is_set():
            temp = self._decode_data(await device_data['temp_characteristic'].read())
            flame = self._decode_data(await device_data['flame_characteristic'].read())
            air = self._decode_data(await device_data['air_characteristic'].read())
            print("Temp: ", str(temp), "Flame: ", str(flame), "Air: ", str(air))
            self.buffer.append({
                'id': name,
                'flame': flame,
                'air': air,
                'temp': temp
            })
            self.mqtt_client.publish(_SENSOR_DATA_TOPIC, b'data rec')
            if len(self.buffer) > 0:
                self.send_buffer_mode.set()
                return
            await asyncio.sleep_ms(5)

    async def __listen_to_device_characteristic(self, name):
        self.mqtt_client.mqtt_client.publish(_SENSOR_DATA_TOPIC, b'data rec')
        device_data = self.device
        while not self.send_buffer_mode.is_set():
            try:
                print(f"Listening to {name}")
                flame, air, temp = await asyncio.gather(
                    device_data['flame_characteristic'].notified(),
                    device_data['air_characteristic'].notified(),
                    device_data['temp_characteristic'].notified(),
                )
                flame = self._decode_data(flame)
                air = self._decode_data(air)
                temp = self._decode_data(temp)
                print(f"Device: {name}, data: {flame}, {air}, {temp}")
                self.buffer.append({
                    'id': name,
                    'flame': flame,
                    'air': air,
                    'temp': temp
                })
                if len(self.buffer) > 0:
                    self.send_buffer_mode.set()
            
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

    def _encode_data(self, data):
        return struct.pack("<h", int(data))
    
    def _decode_data(self, data):
        return struct.unpack("<h", data)[0]
    
class BlePeripheralManager:
    def __init__(self):
        self.start_sending_event = asyncio.Event()
        self.connection_to_send_to = None
        self.devices_to_aggregate = {}
        self.sampling_interval = 5
        self.greendot_service = aioble.Service(_GREENDOT_SERVICE_UUID)
        self.flame_sensor_characteristic = aioble.Characteristic(self.greendot_service, _FLAME_SENSOR_UUID, read=True, write=True, notify=True)
        self.air_sensor_characteristic = aioble.Characteristic(self.greendot_service, _AIR_SENSOR_UUID, read=True, write=True, notify=True)
        self.temp_sensor_characteristic = aioble.Characteristic(self.greendot_service, _TEMP_SENSOR_UUID, read=True, write=True, notify=True)
        aioble.register_services(self.greendot_service)

    async def run(self):
        await asyncio.gather(
            asyncio.create_task(self.__advertise()),
            asyncio.create_task(self.__notify_sensor_data()),
        )

    async def __advertise(self):
        while True:
            print("Starting advertisement...")
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
                print("Sending sensor data...")
                # TODO: Get sensor data
                temp_sensor_data = 1000.999
                flame_sensor_data = 2000.999
                air_sensor_data = 3000.999

                await self.__notify(
                    flame_sensor_data,
                    air_sensor_data,
                    temp_sensor_data
                )

    async def __notify(self, flame, air, temp):
        self.flame_sensor_characteristic.write(self._encode_data(flame))
        self.air_sensor_characteristic.write(self._encode_data(air))
        self.temp_sensor_characteristic.write(self._encode_data(temp))
        self.flame_sensor_characteristic.notify(self.connection_to_send_to)
        self.air_sensor_characteristic.notify(self.connection_to_send_to)
        self.temp_sensor_characteristic.notify(self.connection_to_send_to)
        print("Sent sensor data")
        await asyncio.sleep(self.sampling_interval)
    
    def _encode_data(self, data):
        return struct.pack("<h", int(data))
    
    def _decode_data(self, data):
        return struct.unpack("<h", data)[0]
    

class MqttClient:
    def __init__(self, loop):
        self.client_id = _DEVICE_NAME
        with open("device.crt", 'r') as f:
            self.DEVICE_CERT = f.read()
        with open("private.key", 'r') as f:
            self.PRIVATE_KEY = f.read()
            
        # set config for mqtt_as
        MQTTAS.set_config({
            'server': MQTT_BROKER_ENDPOINT,
            'port': 8883,
            'ssl': True,
            'ssl_params': {
                'key': self.PRIVATE_KEY,
                'cert': self.DEVICE_CERT,
                'server_side': False
            },
            'client_id': _DEVICE_NAME,
            'clean': True
        })

        self.client = MQTTAS.MQTTClient(self.loop, config=MQTTAS.config)
        self.client.set_connected_coro(self.connected_cb)
        self.client.set_connected_coro(self.connected_cb)
        self.client.set_disconnected_coro(self.disconnected_cb)
        self.loop = loop
        
        self.keep_connected()
        self.client.publish(_SENSOR_DATA_TOPIC, b'test')
        
    async def connected_cb(self, client):
        print("MQTT connected")
        await self.subscribe()
        
    async def subscribe(self):
        # Subscribe to necessary topics here
        # await self.client.subscribe('your/subscribe/topic', 1)
        pass
    
    async def disconnected_cb(self, client):
        print("MQTT disconnected")
        
    async def start(self):
        await self.client.connect()
        
    async def publish(self, topic, msg, retain=False, qos=0):
        await self.client.publish(topic, msg, retain, qos)
    
    async def keep_connected(self):
        while True:
            await self.client.connect()
            await asyncio.sleep(10)

    def send_sensor_data(self, data):
        print("Sending sensor data...", self.__encode_data(data))
        self.client.publish(_SENSOR_DATA_TOPIC, 't', qos=1)

    # def __connect_mqtt(self):
    #     ssl_params = {"key":self.PRIVATE_KEY, "cert":self.DEVICE_CERT, "server_side":False}
    #     print("connected to mqtt broker 0")
    #     self.mqtt_client = umqtt.simple.MQTTClient(
    #         client_id=self.client_id,
    #         server= MQTT_BROKER_ENDPOINT,
    #         port=8883,
    #         keepalive=30000,
    #         ssl=True,
    #         ssl_params=ssl_params
    #     )
    #     print("connected to mqtt broker 1")
    #     self.mqtt_client.connect()
    #     print("connected to mqtt broker")

    # async def ping(self):
    #     while True:
    #         self.mqtt_client.ping()
    #         await asyncio.sleep(50)
        

    def __encode_data(self, data):
        return json.dumps(data)
    
    def __decode_data(self, data):
        return json.loads(data)
    

class Node:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        if _DEVICE_MODE == "CENTRAL":
            self._connect_wifi()
            self.mqtt_client = MqttClient(self.loop)
        self.bt_node = BleCentralManager(self.mqtt_client) if _DEVICE_MODE == "CENTRAL" else BlePeripheralManager()

    def _connect_wifi(self):
        self.wifi = network.WLAN(network.STA_IF)
        self.wifi.active(True)
        self.wifi.connect(WIFI_SSID, WIFI_PASS)
        while not self.wifi.isconnected():
            print("connecting to Wifi...")
            time.sleep(5)
        print("Wifi connected", self.wifi.isconnected())
        
    async def _ping_mqtt(self):
        while True:
            self.mqtt_client.ping()
            await asyncio.sleep(2)
            
    
    async def start(self):
        print("starting")
        
        if _DEVICE_MODE == "CENTRAL":
            asyncio.create_task(self.mqtt_client.start())
            await asyncio.gather(
                self.bt_node.run(),
                self.mqtt_client.keep_connected()
            )
        else:
            await self.bt_node.run()

print("Hello world")
gc.collect()
node = Node()
node.loop.run_until_complete(node.start())
