import machine
import bluetooth
import uasyncio as asyncio
import aioble
import json

aioble.config(mtu=512)

# BLE
_GREENDOT_SERVICE_UUID = bluetooth.UUID(0x181A)
_DATA_UUID = bluetooth.UUID(0x2A6A)
_ADV_INTERVAL_MS = 250_000

# Shared
_DEVICE_NAME_PREFIX = "GREENDOT-"
_NODE_ID = 0
_DEVICE_NAME = _DEVICE_NAME_PREFIX + str(_NODE_ID)

MTU=512

class BlePeripheralManager:
    def __init__(self):
        aioble.config(mtu=MTU)
        self.start_sending_event = asyncio.Event()
        self.connection_to_send_to = None
        self.sampling_interval = 5
        self.greendot_service = aioble.Service(_GREENDOT_SERVICE_UUID)
        self.data_characteristic = aioble.Characteristic(self.greendot_service, _DATA_UUID, read=True, write=True, notify=True)
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
            # await connection.disconnected(timeout_ms=None) # waits for a disconnect to happen
            while connection.is_connected() == True:
                    await asyncio.sleep(5)
            self.start_sending_event.clear()
            print("Disconnected. Restarting advertisement...")

    async def __notify_sensor_data(self):
        while True:
            await self.start_sending_event.wait()
            while self.start_sending_event.is_set():
                print("Sending sensor data...")
                # TODO: Get sensor data
                temp_sensor_data = 125.0
                flame_sensor_data = 1
                air_sensor_data = 9495.56732
                humidity_sensor_data = 100.0

                await self.__notify(
                    self.__encode_json_data({
                        'id': _NODE_ID,
                        'temp': temp_sensor_data,
                        'flame': flame_sensor_data,
                        'air': air_sensor_data,
                        'humidity': humidity_sensor_data,
                    })
                )

    async def __notify(self, data):
        self.data_characteristic.write(data)
        self.data_characteristic.notify(self.connection_to_send_to)
        print("Sent sensor data")
        await asyncio.sleep(self.sampling_interval)
    
    def __encode_json_data(self, data):
        return json.dumps(data).encode('utf-8')
class Node:
    def __init__(self):
        self.bt_node = BlePeripheralManager()
    
    async def start(self):
        print("starting")
        await asyncio.create_task(self.bt_node.run())
                
node = Node()
asyncio.run(node.start())