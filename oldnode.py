import machine
import network
import bluetooth
import umqtt.simple
import time
import uasyncio as asyncio
import aioble
import struct
import json

WIFI_SSID = "skku"
WIFI_PASS = "skku1398"
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"

WIFI_TOGGLE_BUTTON_PIN = 14



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
_SENSOR_DATA_TOPIC = "greendot/sensor/data"

class BTClient:
    def __init__(self, mqtt_client, default_mode_event, central_mode_event, peripheral_mode_event):
        self.connected_device_name = None
        self.device = None
        self.connection = None
        self.temp_characteristic = None
        self.flame_characteristic = None
        self.air_characteristic = None
        self.mqtt_client = mqtt_client
        self.default_mode_event = default_mode_event
        self.central_mode_event = central_mode_event
        self.peripheral_mode_event = peripheral_mode_event
        
    async def act_as_central(self):
        try:
            # try to scan and connect for 5 minutes
            await asyncio.wait_for(self._scan_for_nodes(), timeout=_CENTRAL_SCAN_TIMEOUT)
            print("Found device, connecting...")
            await self._connect_to_node()
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
    
    async def _scan_for_nodes(self):
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
    
    async def _connect_to_node(self):
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
        while self.central_mode_event.is_set():
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
            temp = self._decode_data(await self.temp_characteristic.read())
            flame = self._decode_data(await self.flame_characteristic.read())
            air = self._decode_data(await self.air_characteristic.read())
            print("Temp: ", str(temp), "Flame: ", str(flame), "Air: ", str(air))
            self.mqtt_client.send_sensor_data(self.connected_device_name ,temp, flame, air)
            await asyncio.sleep_ms(_READ_INTERVAL_MS)
    
    async def advertise(self):
        while self.peripheral_mode_event.is_set():
            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=_DEVICE_NAME,
                services=[_GREENDOT_SERVICE_UUID],
            ) as connection:
                print("Connection from", connection.device)
                await connection.disconnected()
                print("Disconnected. Restarting advertisement...")

    async def send_sensor_data(self):
        while self.peripheral_mode_event.is_set():
            temp_sensor_data = 1
            flame_sensor_data = 2
            air_sensor_data = 3
            
            temp_sensor_data = self._encode_data(temp_sensor_data)
            flame_sensor_data = self._encode_data(flame_sensor_data)
            air_sensor_data = self._encode_data(air_sensor_data)
            
            self.temp_characteristic.write(temp_sensor_data)
            self.flame_characteristic.write(flame_sensor_data)
            self.air_characteristic.write(air_sensor_data)
            await asyncio.sleep_ms(1000)

    def _encode_data(self, data):
        return struct.pack("<h", int(data))
    
    def _decode_data(self, data):
        return struct.unpack("<h", data)[0]
    
class MqttClient:
    def __init__(self):
        self.client_id = _DEVICE_NAME
        self.dead_nodes_queue = []
        self._connect_mqtt()

    def send_sensor_data(self, nodeId, temp, flame, air):
        self._publish(
            _SENSOR_DATA_TOPIC,
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
        if topic == _STATUS_TOPIC and 'node_id' in data:
            node_id = data['node_id']
            self.dead_nodes_queue.append(node_id)
    
    def pop_dead_node(self):
        if self.dead_nodes_queue:
            self.dead_nodes_queue.pop(0)
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
            self.mqtt_client.will_set(_STATUS_TOPIC, self._encode_data({
                'node_id': self.client_id,
            }), retain=False)
            self.mqtt_client.connect()
            self.mqtt_client.subscribe(_STATUS_TOPIC)
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
    def __init__(self, mqtt_client, default_mode_event, central_mode_event):
        self.mqtt_client = mqtt_client
        self.default_mode_event = default_mode_event
        self.central_mode_event = central_mode_event

    async def read_publish_sensors_data(self):
        while self.default_mode_event.is_set() or self.central_mode_event.is_set():
            temp_sensor_data = 1
            flame_sensor_data = 2
            air_sensor_data = 3
            
            self.mqtt_client.send_sensor_data(_DEVICE_NAME ,temp_sensor_data, flame_sensor_data, air_sensor_data)
            await asyncio.sleep_ms(_READ_INTERVAL_MS)

class Node:
    def __init__(self):
        self.central_mode_event = asyncio.Event()
        self.peripheral_mode_event = asyncio.Event()
        self.default_mode_event = asyncio.Event()
        self._connect_wifi()
        self.mqtt_client = MqttClient()
        self.bt_node = BTClient(self.mqtt_client, self.default_mode_event, self.central_mode_event, self.peripheral_mode_event)
        self.sensor_manager = SensorManager(self.mqtt_client, self.default_mode_event, self.central_mode_event)

    def _connect_wifi(self):
        self.wifi = network.WLAN(network.STA_IF)
        self.wifi.active(True)
        self.wifi.connect(WIFI_SSID, WIFI_PASS)
        while not self.wifi.isconnected():
            print("connecting to Wifi...")
            time.sleep(2)
        print("Wifi connected", self.wifi.isconnected())

    def setup_button(self):
        self.button = machine.Pin(WIFI_TOGGLE_BUTTON_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
        self.button.off()
        self.button.irq(trigger=machine.Pin.IRQ_FALLING, handler=self.toggle_wifi)

    def toggle_wifi(self):
        if self.wifi.isconnected():
            print("Disconnecting from WiFi...")
            self.wifi.disconnect()
        else:
            print("Connecting to WiFi...")
            self._connect_wifi()
        
    async def central_mode(self):
        while True:
            await self.central_mode_event.wait()
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
                self._set_current_mode("default")

    async def peripheral_mode(self):
        while True:
            await self.peripheral_mode_event.wait()
            print("peripheral mode")
            self.bt_node.set_peripheral_service()
            adv = asyncio.create_task(self.bt_node.advertise())
            send_data = asyncio.create_task(self.bt_node.send_sensor_data())
            await asyncio.gather(adv, send_data)

    async def default_mode(self):
        while True:
            await self.default_mode_event.wait()
            await self.sensor_manager.read_publish_sensors_data()

    async def check_and_switch_modes(self):
        while True:
            if self.wifi.isconnected():
                dead_node_id = self.mqtt_client.check_for_dead_node()
                if dead_node_id is not None:
                    self.peripheral_mode_event.clear()
                    self.default_mode_event.clear()
                    if not self.central_mode_event.is_set():
                        self.central_mode_event.set()
                else:
                    self.central_mode_event.clear()
                    self.peripheral_mode_event.clear()
                    if not self.default_mode_event.is_set():
                        self.default_mode_event.set()
            else:
                self.central_mode_event.clear()
                self.default_mode_event.clear()
                if not self.peripheral_mode_event.is_set():
                    self.peripheral_mode_event.set()
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