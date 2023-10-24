import machine
import network
import ubluetooth
import ustruct
import umqtt.simple
import time
import ubinascii
import uos

# wifi_ssid = "Mah iPhone"
# wifi_pass = "THEMAHYIDA"
wifi_ssid = "skku"
wifi_pass = "skku1398"
MQTT_BROKER_ENDPOINT = "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com"

class BTNode:
    def __init__(self):
        self.bt = ubluetooth.BLE()
        self.bt.active(True)
        self.bt.irq(self.bt_irq)
        self.connected_nodes = []
        self.buffer = b''
        self.uuid = self._generate_uuid()
        
    def _generate_uuid(self):
        random_bytes = uos.urandom(16)  # Generate 16 random bytes
        uuid = ubinascii.hexlify(random_bytes)  # Convert bytes to hexadecimal
        return uuid

    def bt_irq(self, event, data):
        # Event handler for Bluetooth events
        if event == ubluetooth.EVT_GAP_CONNECT:
            # A device connected to us
            conn_handle, addr_type, addr = data
            self.connected_nodes.append((conn_handle, addr))
        elif event == ubluetooth.EVT_GAP_DISCONNECT:
            # A device disconnected from us
            conn_handle, addr_type, addr = data
            self.connected_nodes.remove((conn_handle, addr))
        elif event == ubluetooth.EVT_GATTS_WRITE:
            # A device wrote to us, assume it's sensor data
            conn_handle, value_handle, = data
            self.buffer += self.bt.gatts_read(value_handle)

    def advertise(self):
        uuid_bytes = bytes.fromhex(self.uuid.decode('utf-8'))
        adv_payload = b'\x02\x01\x06\x11\x06' + uuid_bytes
        self.bt.gap_advertise(100, adv_payload)

    def send_data(self, conn_handle, data):
        # Send data to a connected node
        self.bt.gattc_write(conn_handle, 0, data)

    def process_buffer(self):
        # Process received data
        while self.buffer:
            length, = ustruct.unpack('<H', self.buffer[:2])
            message = self.buffer[2:2+length]
            self.buffer = self.buffer[2+length:]
            # Return the message for further processing
            return message

class Node:
    def __init__(self):
        self.client_id = "NODE-1"
        self.dht_sensor = machine.ADC(machine.Pin(32))
        self.air_quality_sensor = machine.ADC(machine.Pin(35))
        self.flame_sensor = machine.ADC(machine.Pin(34))
        self.wifi = network.WLAN(network.STA_IF)
        self.wifi.active(True)
        self.bt_node = BTNode()
        self._connect_wifi()
        self._connect_mqtt()

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
            self.mqtt_client.set_callback(self._sub_callback)
            print("connected to mqtt broker")
        except:
            print("error connecting to mqtt broker")
    
    def read_sensors(self):
        return [sensor.read() for sensor in self.sensors]
    
    def send_data(self, data):
        self.mqtt_client.publish("fire/data", data)
    
    def start(self):
        print("starting")

        self.bt_node.advertise()
        start_time = time.time()
        while True:
        #    if self.wifi.isconnected():
        #        data = self.read_sensors()
        #        self.send_data(str(data))
        #        bt_message = self.bt_node.process_buffer()
        #        if bt_message:
        #            self.send_data(bt_message)
        #    else:
        #        for conn_handle, _ in self.bt_node.connected_nodes:
        #            self.bt_node.send_data(conn_handle, str(self.read_sensors()))
            print(self.bt_node.connected_nodes)
            time.sleep(3)
            elapsed_time = time.time() - start_time  # Calculate elapsed time
            if elapsed_time >= 10:  # Check if 30 seconds
                print("30 seconds elapsed, exiting loop.")
                break

print("Hello world")
node = Node()
node.start()
