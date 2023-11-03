import os
import asyncio
from bluepy.btle import Scanner, DefaultDelegate, Peripheral, UUID
import paho.mqtt.client as mqtt
import ssl

# MQTT and BLE Configuration
WIFI_SSID = "skku"
WIFI_PASS = "skku1398"
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"
SENSOR_DATA_TOPIC = 'greendot/sensor/data'

DEVICE_NAME_PREFIX = "GREENDOT-"
GREENDOT_SERVICE_UUID = "0000181A-0000-1000-8000-00805f9b34fb"
FLAME_SENSOR_UUID = "00002A6A-0000-1000-8000-00805f9b34fb"
TEMP_SENSOR_UUID = "00002A6B-0000-1000-8000-00805f9b34fb"
AIR_SENSOR_UUID = "00002A6C-0000-1000-8000-00805f9b34fb"

CA_CERTS_PATH = "./AmazonRootCA1.pem"  # Root CA certificate
CERTFILE_PATH = "./device.pem.crt"  # Client certificate
KEYFILE_PATH = "./private.pem.key"  # Private key

def toggle_wifi(state):
    os.system(f"sudo ifconfig wlan0 {'up' if state else 'down'}")

def toggle_bluetooth(state):
    os.system(f"sudo systemctl {'start' if state else 'stop'} bluetooth")

# MQTT Manager with asyncio support
class AsyncMQTTManager:
    def __init__(self, broker_endpoint, loop):
        self.loop = loop
        self.client = mqtt.Client()
        self.client.tls_set(ca_certs=CA_CERTS_PATH,
                            certfile=CERTFILE_PATH,
                            keyfile=KEYFILE_PATH,
                            tls_version=ssl.PROTOCOL_TLSv1_2)
        self.client.tls_insecure_set(False)
        self.client.connect(broker_endpoint, port=8883)

    async def publish(self, topic, message):
        result, mid = await self.loop.run_in_executor(None, self.client.publish, topic, message)
        return result


# BLE Delegate to handle Notifications
class NotificationDelegate(DefaultDelegate):
    def __init__(self, mqtt_manager, loop):
        DefaultDelegate.__init__(self)
        self.mqtt_manager = mqtt_manager
        self.loop = loop

    async def handle_notification(self, cHandle, data):
        print("Received notification from handle: {}".format(data))
        # asyncio.run_coroutine_threadsafe(
        #     self.mqtt_manager.publish(SENSOR_DATA_TOPIC, data),
        #     self.mqtt_manager.loop
        # )
        asyncio.run_coroutine_threadsafe(self.async_handle_notification(data), self.loop)

    async def async_handle_notification(self, data):
        # Now we're in async context, we can await coroutines
        try:
            await self.mqtt_manager.publish(SENSOR_DATA_TOPIC, data)
            print(f"Published data to {SENSOR_DATA_TOPIC}")
        except Exception as e:
            print(f"Failed to publish data: {e}")

# BLE Manager with asyncio support
class AsyncBLEManager:
    def __init__(self, device_name_prefix, mqtt_manager, loop):
        self.loop = loop
        self.device_name_prefix = device_name_prefix
        self.mqtt_manager = mqtt_manager
        self.devices_to_connect = []

    async def scan_for_devices(self):
        scanner = Scanner()
        devices = await self.loop.run_in_executor(None, scanner.scan, 10.0)
        for dev in devices:
            for (adtype, desc, value) in dev.getScanData():
                if value.startswith(self.device_name_prefix):
                    self.devices_to_connect.append(dev.addr)
                    print(f"Found BLE device with address: {dev.addr} {value}")
                    # await self.handle_device_connection(dev.addr)

    async def connect_and_listen(self):
        # toggle_wifi(False)
        print(1)
        tasks = [self.loop.create_task(self.handle_device_connection(addr)) for addr in self.devices_to_connect]
        print(2)
        await asyncio.gather(*tasks)
        print("2 end")

    async def handle_device_connection(self, addr):
        print(3)
        while True:
            try:
                print(4, addr)
                self.peripheral = Peripheral(addr)
                print(5)
                notification_delegate = NotificationDelegate(self.mqtt_manager, self.loop)
                print(6)
                self.peripheral.setDelegate(notification_delegate)
                print(7)
                # await self.loop.run_in_executor(None, peripheral.setDelegate, NotificationDelegate(self.mqtt_manager))
                # peripheral = Peripheral(addr)
                # peripheral.setDelegate(NotificationDelegate(self.mqtt_manager))
                services = await self.loop.run_in_executor(None, self.peripheral.getServices)
                print(8)
                for service in services:
                    print(9)
                    if service.uuid == UUID(GREENDOT_SERVICE_UUID):
                        print(10)
                        characteristics = await self.loop.run_in_executor(None, service.getCharacteristics)
                        print(11)
                        for char in characteristics:
                            print(12)
                            if char.uuid in [UUID(FLAME_SENSOR_UUID), UUID(TEMP_SENSOR_UUID), UUID(AIR_SENSOR_UUID)]:
                                print(13)
                                await self.loop.run_in_executor(None, self.peripheral.writeCharacteristic, char.getHandle() + 1, b"\x01\x00")
                                print(14)
                                while True:
                                    print(15)
                                    await self.loop.run_in_executor(None, self.peripheral.waitForNotifications, 1.0)
            except Exception as e:
                print(f"Connection to {addr} failed: {e}")
                await asyncio.sleep(5)

# Node Manager with asyncio support
class AsyncNodeManager:
    def __init__(self, ble_manager, mqtt_manager):
        self.ble_manager = ble_manager
        self.mqtt_manager = mqtt_manager

    async def run(self):
        await self.ble_manager.scan_for_devices()
        await self.ble_manager.connect_and_listen()

# Main execution with asyncio event loop
async def main():
    loop = asyncio.get_running_loop()
    mqtt_manager = AsyncMQTTManager(MQTT_BROKER_ENDPOINT, loop)
    ble_manager = AsyncBLEManager(DEVICE_NAME_PREFIX, mqtt_manager, loop)
    node_manager = AsyncNodeManager(ble_manager, mqtt_manager)
    await node_manager.run()

if __name__ == "__main__":
    asyncio.run(main())
    
