from bluepy import btle
from bluepy.btle import Scanner, DefaultDelegate
import paho.mqtt.client as mqtt
import threading
import time

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

# MQTT Manager
class MQTTManager:
    def __init__(self, broker_endpoint):
        self.client = mqtt.Client()
        self.client.connect(broker_endpoint)
    
    def publish(self, topic, message):
        self.client.publish(topic, message)

# BLE Delegate to handle Notifications
class NotificationDelegate(DefaultDelegate):
    def __init__(self, mqtt_manager):
        DefaultDelegate.__init__(self)
        self.mqtt_manager = mqtt_manager

    def handleNotification(self, cHandle, data):
        print("Notification:", str(data))
        self.mqtt_manager.publish(SENSOR_DATA_TOPIC, data)

# BLE Manager using bluepy
class BLEManager:
    def __init__(self, device_name_prefix, mqtt_manager):
        self.device_name_prefix = device_name_prefix
        self.mqtt_manager = mqtt_manager
        self.devices_to_connect = []
    
    def scan_for_devices(self):
        scanner = Scanner()
        devices = scanner.scan(10.0)
        for dev in devices:
            for (adtype, desc, value) in dev.getScanData():
                if desc == "Complete Local Name" and value.startswith(self.device_name_prefix):
                    self.devices_to_connect.append(dev.addr)
                    print(f"Found BLE device with address: {dev.addr}")

    def connect_and_listen(self):
        for addr in self.devices_to_connect:
            print(f"Connecting to {addr}")
            peripheral = btle.Peripheral(addr)
            peripheral.setDelegate(NotificationDelegate(self.mqtt_manager))

            try:
                # Assuming all characteristics use notify property and have descriptors to enable notifications
                for svc in peripheral.getServices():
                    if svc.uuid == btle.UUID(GREENDOT_SERVICE_UUID):
                        for char in svc.getCharacteristics():
                            if char.uuid in [btle.UUID(FLAME_SENSOR_UUID), btle.UUID(TEMP_SENSOR_UUID), btle.UUID(AIR_SENSOR_UUID)]:
                                peripheral.writeCharacteristic(char.getHandle() + 1, b"\x01\x00")
                                while True:
                                    if peripheral.waitForNotifications(1.0):
                                        continue
            except Exception as e:
                print(f"Connection to {addr} failed: {e}")

# Node Manager
class NodeManager:
    def __init__(self, ble_manager, mqtt_manager):
        self.ble_manager = ble_manager
        self.mqtt_manager = mqtt_manager

    def run(self):
        # Run BLE scanning and connection in a separate thread
        threading.Thread(target=self.ble_manager.scan_for_devices).start()
        time.sleep(5)  # Give some time for the scan to complete
        threading.Thread(target=self.ble_manager.connect_and_listen, args=(self.mqtt_manager,)).start()

# Main execution
if __name__ == "__main__":
    mqtt_manager = MQTTManager(MQTT_BROKER_ENDPOINT)
    ble_manager = BLEManager(DEVICE_NAME_PREFIX)
    node_manager = NodeManager(ble_manager, mqtt_manager)
    node_manager.run()