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

wifi_ssid = "skku"
wifi_pass = "skku1398"
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"


_GREENDOT_SERVICE_UUID = bluetooth.UUID(0x181A)

_FLAME_SENSOR_UUID = bluetooth.UUID(0x2A6A)
_TEMP_SENSOR_UUID = bluetooth.UUID(0x2A6B)
_AIR_SENSOR_UUID = bluetooth.UUID(0x2A6C)

_ADV_DURATION_S = 30
_ADV_INTERVAL_MS = 250_000
_READ_INTERVAL_MS = 2000

_DEVICE_NAME_PREFIX = "GREENDOT-"
_DEVICE_NAME = _DEVICE_NAME_PREFIX + "NODE-2"


class BTNode:
    def __init__(self):
        self.connected_device_name = None
        self.device = None
        self.connection = None
        self.temp_characteristic = None
        self.flame_characteristic = None
        self.air_characteristic = None
        
    async def act_as_central(self):
        await self.__scan_for_nodes()
        print("Found device, connecting...")
        await self.__connect_to_node()
        print("Connected, recieving data...")
        while True:
            await self.__recieve()
            await asyncio.sleep_ms(_READ_INTERVAL_MS)
    
    async def act_as_peripheral(self):
        greendot_service = aioble.Service(_GREENDOT_SERVICE_UUID)
        self.temp_characteristic = aioble.Characteristic(greendot_service, _TEMP_SENSOR_UUID, read=True, notify=True)
        self.flame_characteristic = aioble.Characteristic(greendot_service, _FLAME_SENSOR_UUID, read=True, notify=True)
        self.air_characteristic = aioble.Characteristic(greendot_service, _AIR_SENSOR_UUID, read=True, notify=True)

        aioble.register_services(greendot_service)
        adv = asyncio.create_task(self.__advertise())
        send_data = asyncio.create_task(self.__send_sensor_data())
        await asyncio.gather(adv,send_data)
        return
    
    async def __scan_for_nodes(self):
        # Scan for 5 seconds, in active mode, with very low interval/window (to
        # maximise detection rate).
        async with aioble.scan(5000, interval_us=30000, window_us=30000, active=True) as scanner:
            async for result in scanner:
                # See if it matches our name and the environmental sensing service.
                if _DEVICE_NAME_PREFIX in result.name() and _GREENDOT_SERVICE_UUID in result.services():
                    self.connected_device_name = result.name()
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
        
    async def __recieve(self):
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
        return temp, flame, air
    
    async def __advertise(self):
        end_time = time.time() + _ADV_DURATION_S
        while True:
            async with await aioble.advertise(
                _ADV_INTERVAL_MS,
                name=_DEVICE_NAME,
                services=[_GREENDOT_SERVICE_UUID],
            ) as connection:
                print("Connection from", connection.device)
                await connection.disconnected()
                print("Disconnected. Restarting advertisement...")
    async def __send_sensor_data(self):
        while True:
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

class Node:
    def __init__(self):
        self.client_id = "NODE-1"
        # self.dht_sensor = machine.ADC(machine.Pin(32))
        # self.air_quality_sensor = machine.ADC(machine.Pin(35))
        # self.flame_sensor = machine.ADC(machine.Pin(34))
        # self.wifi = network.WLAN(network.STA_IF)
        # self.wifi.active(True)
        self.bt_node = BTNode()
        # self._connect_wifi()
        # self._connect_mqtt()d

    def _connect_wifi(self):
        self.wifi.connect(wifi_ssid, wifi_pass)
        while not self.wifi.isconnected():
            print("connecting to Wifi...")
            time.sleep(5)
            break
        print("Wifi connected", self.wifi.isconnected())
       
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
            self.mqtt_client.connect()
            print("connected to mqtt broker")
        except:
            print("error connecting to mqtt broker")
    
    
    async def start(self):
        print("starting")
        # while True:
        #    if self.wifi.isconnected():
        #        data = self.read_sensors()
        #        self.send_data(str(data))
        #        bt_message = self.bt_node.process_buffer()
        #        if bt_message:
        #            self.send_data(bt_message)
        #    else:
        #        for conn_handle, _ in self.bt_node.connected_nodes:
        #            self.bt_node.send_data(conn_handle, str(self.read_sensors()))
        self.bt_node.act_as_central()

print("Hello world")
node = Node()
asyncio.run(node.start())
