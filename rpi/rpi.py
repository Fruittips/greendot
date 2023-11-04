import os
import asyncio
from bluepy.btle import Scanner, DefaultDelegate, Peripheral, UUID, BTLEDisconnectError, BTLEException
import paho.mqtt.client as mqtt
import json
import time

from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder

# MQTT and BLE Configuration
MTU = 512

# ESP32 Configuration (Peripheral devices)
DEVICE_NAME_PREFIX = "GREENDOT-"
GREENDOT_SERVICE_UUID = "0000181A-0000-1000-8000-00805f9b34fb"
SENSOR_DATA_UUID = "00002A6A-0000-1000-8000-00805f9b34fb"
FLAME_PRESENCE_UUID = "0000A1F3-0000-1000-8000-00805f9b34fb" #for broacasting flame presence

# AWS IoT Client configuration
CA_CERTS_PATH = "./certs/AmazonRootCA1.pem"  # Root CA certificate
CERTFILE_PATH = "./certs/device.pem.crt"  # Client certificate
KEYFILE_PATH = "./certs/private.pem.key"  # Private key

MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"
CLIENT_ID = "GREENDOT-RPI"  # Name for the Thing in AWS IoT
SENSOR_DATA_TOPIC = 'greendot/sensor/data'
FLAME_PRESENCE_TOPIC = "greendot/status"


# MQTT Manager with asyncio support
class AsyncMQTTManager:
    def __init__(self, broker_endpoint, client_id, loop):
        self.loop = loop
        self.client = self._establish_connection(broker_endpoint, client_id)
        self.subscribe()
        
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
            print(f"Error connecting or subscribing MQTT: {e}")
            
        return mqtt_connection
        
    def publish(self, topic, message):
        self.client.publish(topic, json.dumps(message), mqtt.QoS.AT_LEAST_ONCE)
        print("Published: '" + json.dumps(message) + "' to the topic: " + SENSOR_DATA_TOPIC + " for client: " + CLIENT_ID)
        
    def subscribe(self):
        print("Subscribing to topic '{}'...".format(FLAME_PRESENCE_TOPIC))
        self.client.subscribe(FLAME_PRESENCE_TOPIC, mqtt.QoS.AT_LEAST_ONCE, self._subscribe_callback)
        
    def attach_ble_manager(self, ble_manager):
        self.ble_manager = ble_manager
    
    def _subscribe_callback(self, topic, payload):
        print("Received message from topic '{}': {}".format(topic, payload))
        asyncio.run_coroutine_threadsafe(self.ble_manager.broadcast_to_peripherals(payload.decode()), self.loop)

    

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
        try:
            data = self.__decode_json_data(data)
            #add current time
            data['timestamp'] = time.time()
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
        self.connected_peripherals = {}

    async def scan_for_devices(self):
        while True:
            try: 
                scanner = Scanner()
                devices = await self.loop.run_in_executor(None, scanner.scan, 10.0)
                for dev in devices:
                    for (adtype, desc, value) in dev.getScanData():
                        if value.startswith(self.device_name_prefix):
                            self.devices_to_connect.append(dev.addr)
                            print(f"Found BLE device with address: {dev.addr} {value}")
                break
            except BTLEException as e:
                print(f"[ERROR SCANNING]: {e}")
                continue
            except Exception as e:
                print(f"Failed to scan for BLE devices: {e}")
                continue

    async def connect_and_listen(self):
        tasks = [self.loop.create_task(self.handle_device_connection(addr)) for addr in self.devices_to_connect]
        await asyncio.gather(*tasks)

    async def handle_device_connection(self, addr):
        print("Connecting to", addr, "...")
        while True:
            try:
                self.connected_peripherals[addr] = Peripheral(addr)
                self.connected_peripherals[addr].setMTU(MTU)
                print("[CONNECTED] to", addr)
                notification_delegate = NotificationDelegate(self.mqtt_manager, self.loop)
                self.connected_peripherals[addr].setDelegate(notification_delegate)
                services = await self.loop.run_in_executor(None, self.connected_peripherals[addr].getServices)
                for service in services:
                    if service.uuid == UUID(GREENDOT_SERVICE_UUID):
                        characteristics = await self.loop.run_in_executor(None, service.getCharacteristics)
                        for char in characteristics:
                            if char.uuid == UUID(SENSOR_DATA_UUID):
                                await self.loop.run_in_executor(None, self.connected_peripherals[addr].writeCharacteristic, char.getHandle() + 1, b"\x01\x00")
                                while True:
                                    await self.loop.run_in_executor(None, self.connected_peripherals[addr].waitForNotifications, 1.0)
                print("[AT BOTTOM LOOP]")
            except Exception as e:
                print(f"Connection to {addr} failed: {e}")
                self.connected_peripherals[addr].disconnect()
                self.connected_peripherals.pop(addr, None)
                print ("[DISCONNECTED] from ", addr)
                print ("[RECONNECTING] to ", addr, "in 5 seconds...")
                await asyncio.sleep(5)
                
    async def broadcast_to_peripherals (self, message):
        print("message to broadcast: ", message)
        for addr, peripheral in self.connected_peripherals.items():
            try:
                # retrieve flam characteristic handle
                services = await self.loop.run_in_executor(None, peripheral.getServices)
                for service in services:
                    if service.uuid == UUID(GREENDOT_SERVICE_UUID):
                        characteristics = await self.loop.run_in_executor(None, service.getCharacteristics)
                        for char in characteristics:
                            if char.uuid == UUID(FLAME_PRESENCE_UUID):
                                print("broadcasting to ", addr)
                                print ("bytes message is this RPI",bytes(message, 'utf-8'))
                                await self.loop.run_in_executor(None, peripheral.writeCharacteristic, char.getHandle(), bytes(message, 'utf-8'))
            except Exception as e:
                print(f"Failed to broadcast to {addr}: {e}")
                await asyncio.sleep(2)

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
    mqtt_manager.attach_ble_manager(ble_manager)
    node_manager = AsyncNodeManager(ble_manager, mqtt_manager)
    await node_manager.run()
    

if __name__ == "__main__":
    asyncio.run(main())