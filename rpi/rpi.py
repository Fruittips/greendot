import os
import asyncio
from bluepy.btle import Scanner, DefaultDelegate, Peripheral, UUID, BTLEDisconnectError
import paho.mqtt.client as mqtt
import ssl
import json
import struct
import time

from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder

# MQTT and BLE Configuration
WIFI_SSID = "skku"
WIFI_PASS = "skku1398"
MTU = 512

# ESP32 Configuration (Peripheral devices)
DEVICE_NAME_PREFIX = "GREENDOT-"
GREENDOT_SERVICE_UUID = "0000181A-0000-1000-8000-00805f9b34fb"
FLAME_SENSOR_UUID = "00002A6A-0000-1000-8000-00805f9b34fb"
TEMP_SENSOR_UUID = "00002A6B-0000-1000-8000-00805f9b34fb"
AIR_SENSOR_UUID = "00002A6C-0000-1000-8000-00805f9b34fb"

# AWS IoT Client configuration
CA_CERTS_PATH = "./certs/AmazonRootCA1.pem"  # Root CA certificate
CERTFILE_PATH = "./certs/device.pem.crt"  # Client certificate
KEYFILE_PATH = "./certs/private.pem.key"  # Private key

MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"
CLIENT_ID = "GREENDOT-RPI"  # Name for the Thing in AWS IoT
SENSOR_DATA_TOPIC = 'greendot/sensor/data'


# MQTT Manager with asyncio support
class AsyncMQTTManager:
    def __init__(self, broker_endpoint, client_id, loop):
        self.loop = loop
        self.client = self._establish_connection(broker_endpoint, client_id)
        
        
    def _establish_connection(self, broker_endpoint, client_id):
        event_loop_group = io.EventLoopGroup(1)
        host_resolver = io.DefaultHostResolver(event_loop_group)
        client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)
        mqtt_connection = mqtt_connection_builder.mtls_from_path(
                endpoint=broker_endpoint,
                cert_filepath=CERTFILE_PATH,
                pri_key_filepath=KEYFILE_PATH,
                client_bootstrap=client_bootstrap,
                ca_filepath=CA_CERTS_PATH,
                client_id=client_id,
                clean_session=False,
                keep_alive_secs=6
                )
        
        print("Connecting to {} with client ID '{}'...".format(broker_endpoint, client_id))
        try:
            connect_future = mqtt_connection.connect()
            connect_future.result()
            print("Connected to MQTT broker!")
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")
            # print("Retrying in 5 seconds...")
            # time.sleep(5)
            # self._establish_connection()
        return mqtt_connection
        

    def publish(self, topic, message):
        print("line 70, data", message)
        print('Publishing message to topic: ' + topic + ' with message: ' + json.dumps(message) + ' for client: ' + CLIENT_ID + '...')
        self.client.publish(topic, json.dumps(message), mqtt.QoS.AT_LEAST_ONCE)
        print("Published: '" + json.dumps(message) + "' to the topic: " + SENSOR_DATA_TOPIC + " for client: " + CLIENT_ID)



# BLE Delegate to handle Notifications
class NotificationDelegate(DefaultDelegate):
    def __init__(self, mqtt_manager, loop):
        DefaultDelegate.__init__(self)
        self.mqtt_manager = mqtt_manager
        self.loop = loop

    def handleNotification(self, cHandle, data):
        print("Received notification from handle: {} with data {}".format(cHandle,data))
        asyncio.run_coroutine_threadsafe(self.async_handle_notification(data), self.loop)

    async def async_handle_notification(self, data):
        # Now we're in async context, we can await coroutines
        try:
            # data = struct.unpack('<h', data)[0]
            print("96 [BEFORE DECODE] ESP32:", data)
            data = self.__decode_json_data(data)
            print("98 [AFTER DECODE] ESP32:", data)
            self.mqtt_manager.publish(SENSOR_DATA_TOPIC,data)
        except Exception as e:
            print(f"Failed to publish data: {e}")
            
    def __decode_json_data(self, data):
        return json.loads(data.decode('utf-8'))

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
                self.peripheral.setMTU(MTU)
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
                            if char.uuid == UUID(FLAME_SENSOR_UUID):
                                print(13)
                                await self.loop.run_in_executor(None, self.peripheral.writeCharacteristic, char.getHandle() + 1, b"\x01\x00")
                                print(14)
                                while True:
                                    print(15)
                                    await self.loop.run_in_executor(None, self.peripheral.waitForNotifications, 1.0)
            except Exception as e:
                print(f"Connection to {addr} failed: {e}")
                await asyncio.sleep(5)
            except BTLEDisconnectError as err:
                print(f"Except block caught Connection to {addr} disconnected: {err}")
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
    mqtt_manager = AsyncMQTTManager(MQTT_BROKER_ENDPOINT, CLIENT_ID, loop)
    ble_manager = AsyncBLEManager(DEVICE_NAME_PREFIX, mqtt_manager, loop)
    node_manager = AsyncNodeManager(ble_manager, mqtt_manager)
    await node_manager.run()
    

if __name__ == "__main__":
    asyncio.run(main())