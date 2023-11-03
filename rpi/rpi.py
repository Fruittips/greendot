import asyncio
from bluepy.btle import Scanner, DefaultDelegate, Peripheral, UUID
import paho.mqtt.client as mqtt
import threading
import time
import ssl

# MQTT and BLE Configuration
WIFI_SSID = "skku"
WIFI_PASS = "skku1398"
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"
SENSOR_DATA_TOPIC = 'greendot/sensor/data'

DEVICE_NAME_PREFIX = "GREENDOT-"
GREENDOT_SERVICE_UUID = "0000181A-0000-1000-8000-00805f9b34fb"
DATA_UUID = "00002A6A-0000-1000-8000-00805f9b34fb"
FLAME_SENSOR_UUID = "00002A6A-0000-1000-8000-00805f9b34fb"
TEMP_SENSOR_UUID = "00002A6B-0000-1000-8000-00805f9b34fb"
AIR_SENSOR_UUID = "00002A6C-0000-1000-8000-00805f9b34fb"

CA_CERTS_PATH = "./AmazonRootCA1.pem"  # Root CA certificate
CERTFILE_PATH = "./device.pem.crt"  # Client certificate
KEYFILE_PATH = "./private.pem.key"  # Private key

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
        func = lambda: self.client.publish(topic, message)
        await self.loop.run_in_executor(None, func)

# BLE Delegate to handle Notifications
class NotificationDelegate(DefaultDelegate):
    def __init__(self, mqtt_manager):
        DefaultDelegate.__init__(self)
        self.mqtt_manager = mqtt_manager

    def handleNotification(self, cHandle, data):
        asyncio.run_coroutine_threadsafe(
            self.mqtt_manager.publish(SENSOR_DATA_TOPIC, data),
            self.mqtt_manager.loop
        )

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
                if desc == "Complete Local Name" and value.startswith(self.device_name_prefix):
                    self.devices_to_connect.append(dev.addr)
                    print(f"Found BLE device with address: {dev.addr}")

    async def connect_and_listen(self):
        tasks = [self.loop.create_task(self.handle_device_connection(addr)) for addr in self.devices_to_connect]
        await asyncio.gather(*tasks)

    async def handle_device_connection(self, addr):
        while True:
            try:
                peripheral = Peripheral(addr)
                peripheral.setDelegate(NotificationDelegate(self.mqtt_manager))
                # ... [Setting up characteristics and enabling notifications]

                while True:
                    await self.loop.run_in_executor(None, peripheral.waitForNotifications, 1.0)
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