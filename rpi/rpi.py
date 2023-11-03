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

# MQTT Manager
class MQTTManager:
    def __init__(self, broker_endpoint):
        self.client = mqtt.Client()
        # Configure TLS set
        self.client.tls_set(ca_certs=CA_CERTS_PATH,
                            certfile=CERTFILE_PATH,
                            keyfile=KEYFILE_PATH,
                            tls_version=ssl.PROTOCOL_TLSv1_2)

        # TLS options
        self.client.tls_insecure_set(False)  # Set to True if the broker's domain name does not match the certificate

        # Connect with SSL/TLS
        self.client.connect(broker_endpoint, port=8883)  # As
    
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
            # Start each device connection in its own daemon thread
            device_thread = threading.Thread(target=self.handle_device_connection, args=(addr,))
            device_thread.setDaemon(True)
            device_thread.start()
    
    def handle_device_connection(self, addr):
        while True:
            try:
                print(f"Connecting to {addr}")
                peripheral = Peripheral(addr)
                peripheral.setDelegate(NotificationDelegate(self.mqtt_manager))
                
                # Assuming all characteristics use notify property and have descriptors to enable notifications
                for svc in peripheral.getServices():
                    if svc.uuid == UUID(GREENDOT_SERVICE_UUID):
                        for char in svc.getCharacteristics():
                            if char.uuid in [UUID(FLAME_SENSOR_UUID), UUID(TEMP_SENSOR_UUID), UUID(AIR_SENSOR_UUID)]:
                                peripheral.writeCharacteristic(char.getHandle() + 1, b"\x01\x00")
                                while True:
                                    if peripheral.waitForNotifications(1.0):
                                        continue
            except Exception as e:
                print(f"Connection to {addr} failed: {e}")
                print("Attempting to reconnect...")
                time.sleep(5)  # Wait for 5 seconds before trying to reconnect


# Node Manager
class NodeManager:
    def __init__(self, ble_manager, mqtt_manager):
        self.ble_manager = ble_manager
        self.mqtt_manager = mqtt_manager

    def run(self):
        # Start the BLE scanning in a separate thread
        ble_scan_thread = threading.Thread(target=self.ble_manager.scan_for_devices)
        ble_scan_thread.setDaemon(True)
        ble_scan_thread.start()

        # Give some time for the scan to complete
        ble_scan_thread.join(timeout=15)

        # Then start the connection/listening threads
        self.ble_manager.connect_and_listen()


# Main execution
if __name__ == "__main__":
    mqtt_manager = MQTTManager(MQTT_BROKER_ENDPOINT)
    ble_manager = BLEManager(DEVICE_NAME_PREFIX, mqtt_manager)
    node_manager = NodeManager(ble_manager, mqtt_manager)
    node_manager.run()