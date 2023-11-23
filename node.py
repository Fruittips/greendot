import machine
import bluetooth
import uasyncio as asyncio
import aioble
import json
from sensors import SensorsManager

# BLE
_GREENDOT_SERVICE_UUID = bluetooth.UUID(0x181A)
_DATA_UUID = bluetooth.UUID(0x2A6A)
_FLAME_PRESENCE_UUID = bluetooth.UUID(0xA1F3)
_ADV_INTERVAL_MS = 250_000
MTU=512

# Shared
_DEVICE_NAME_PREFIX = "GREENDOT-"
_NODE_ID = 0
_DEVICE_NAME = _DEVICE_NAME_PREFIX + str(_NODE_ID)

# Sampling intervals
_SAMPLING_INTERVAL_LOW = 10
_SAMPLING_INTERVAL_HIGH = 5

# Frequencies
_FREQ_HIGH = 160000000 # 160 MHz
_FREQ_LOW = 80000000 # 80 MHz

# Sensors
_FLAME_PIN = 4
_TEMP_HUMIDITY_PIN = 5
_AIR_PIN = 15


class BlePeripheralManager:
    def __init__(self):
        aioble.config(mtu=MTU)
        self.start_sending_event = asyncio.Event()
        self.connection_to_send_to = None
        self.sampling_interval = _SAMPLING_INTERVAL_LOW
        self.greendot_service = aioble.Service(_GREENDOT_SERVICE_UUID)
        self.data_characteristic = aioble.Characteristic(self.greendot_service, _DATA_UUID, read=True, write=True, notify=True)
        self.flame_presence_characteristic = aioble.Characteristic(self.greendot_service, _FLAME_PRESENCE_UUID, read=True, write=True, notify=True, capture=True)
        aioble.register_services(self.greendot_service)
        self.sensors_manager = SensorsManager(_FLAME_PIN, _TEMP_HUMIDITY_PIN, _AIR_PIN)

    async def run(self):
        machine.freq(_FREQ_LOW) # set clock frequency
        await asyncio.gather(
            asyncio.create_task(self.__advertise()),
            asyncio.create_task(self.__notify_sensor_data()),
            asyncio.create_task(self.__listen_to_flame_presence())
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
            while connection.is_connected() == True:
                    await asyncio.sleep(5)
            self.start_sending_event.clear()
            print("Disconnected. Restarting advertisement...")

    async def __notify_sensor_data(self):
        while True:
            try:
                await self.start_sending_event.wait()
                while self.start_sending_event.is_set():
                    
                    print("trying to read sensor values....")
                    
                    temp_humidity_reading = None
                    air_reading = None
                    flame_reading = None
                    try:
                       temp_humidity_reading = self.sensors_manager.get_temp_humidity()
                    except Exception as e:
                        print("Error reading sensor values:", e)
                        await asyncio.sleep(5)
                        continue
                    try:
                       air_reading = self.sensors_manager.get_air_quality(temp_humidity_reading[0],temp_humidity_reading[1])
                    except Exception as e:
                        print("Error reading sensor values:", e)
                        await asyncio.sleep(5)
                        continue
                    try:
                       flame_reading = self.sensors_manager.get_flame_presence()
                    except Exception as e:
                        print("Error reading sensor values:", e)
                        await asyncio.sleep(5)
                        continue
                    
                    # temp_humidity_reading = self.sensors_manager.get_temp_humidity()
                    # air_reading = self.sensors_manager.get_air_quality(temp_humidity_reading[0], temp_humidity_reading[1])
                    # flame_reading = self.sensors_manager.get_flame_presence()
                    
                    await self.__notify(
                        self.__encode_json_data({
                            'id': _NODE_ID,
                            'air': air_reading,
                            'temp': temp_humidity_reading[0],
                            'humidity': temp_humidity_reading[1],
                            'flame': flame_reading,
                        })
                    )
            except Exception as e:
                print("Error sending sensor data:", e)
                await asyncio.sleep(5)
            

    async def __notify(self, data):
        print("Sending sensor data...")
        print(f"Sending {data} to {self.connection_to_send_to}")
        
        self.data_characteristic.write(data)
        self.data_characteristic.notify(self.connection_to_send_to)
        print("Sent sensor data")
        
        await asyncio.sleep(self.sampling_interval)
    
    async def __listen_to_flame_presence(self):
        while True:
            try:
                _, flame_presence_data = await self.flame_presence_characteristic.written()                
                if len(flame_presence_data) > 0:
                    flame_presence = self.__decode_json_data(self.flame_presence_characteristic.read())
                    print("Flame presence characteristic value:",flame_presence)
                    if flame_presence["status"] == "1":
                        print("Flame detected. Increasing sampling interval and clock frequency.")
                        self.sampling_interval = _SAMPLING_INTERVAL_HIGH
                        machine.freq(_FREQ_HIGH) 
                        print(f"Sampling interval: {self.sampling_interval} seconds", f"Clock frequency: {machine.freq()}")
                    elif flame_presence["status"] == "0":
                        print("No flame detected. Decreasing sampling interval and clock frequency.")
                        self.sampling_interval = _SAMPLING_INTERVAL_LOW
                        machine.freq(_FREQ_LOW)
                        print(f"Sampling interval: {self.sampling_interval} seconds", f"Clock frequency: {machine.freq()}")
                    
                await asyncio.sleep(1)
            except Exception as e:
                print("Error listening to flame presence characteristic:", e)
                await asyncio.sleep(5)
    
    def __encode_json_data(self, data):
        return json.dumps(data).encode('utf-8')

    def __decode_json_data(self, data):
        return json.loads(data.decode('utf-8'))
    
class Node:
    def __init__(self):
        self.bt_node = BlePeripheralManager()
    
    async def start(self):
        print("starting")
        await asyncio.create_task(self.bt_node.run())
              
node = Node()
asyncio.run(node.start())