# BLE Manager using bluepy
class BLEManager:
    # ... [rest of your class] ...

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
                peripheral = btle.Peripheral(addr)
                peripheral.setDelegate(NotificationDelegate(self.mqtt_manager))
                # ... [rest of your connection and listening code] ...
            except Exception as e:
                print(f"Connection to {addr} failed: {e}")
                print("Attempting to reconnect...")
                time.sleep(5)  # Wait for 5 seconds before trying to reconnect

# Node Manager
class NodeManager:
    # ... [rest of your class] ...

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
