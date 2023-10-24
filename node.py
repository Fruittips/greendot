import machine
import network
import ubluetooth
import ustruct
import umqtt.simple
import time
import ubinascii
import uos

from micropython import const
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_GATTS_READ_REQUEST = const(4)
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)
_IRQ_PERIPHERAL_CONNECT = const(7)
_IRQ_PERIPHERAL_DISCONNECT = const(8)
_IRQ_GATTC_SERVICE_RESULT = const(9)
_IRQ_GATTC_SERVICE_DONE = const(10)
_IRQ_GATTC_CHARACTERISTIC_RESULT = const(11)
_IRQ_GATTC_CHARACTERISTIC_DONE = const(12)
_IRQ_GATTC_DESCRIPTOR_RESULT = const(13)
_IRQ_GATTC_DESCRIPTOR_DONE = const(14)
_IRQ_GATTC_READ_RESULT = const(15)
_IRQ_GATTC_READ_DONE = const(16)
_IRQ_GATTC_WRITE_DONE = const(17)
_IRQ_GATTC_NOTIFY = const(18)
_IRQ_GATTC_INDICATE = const(19)
_IRQ_GATTS_INDICATE_DONE = const(20)
_IRQ_MTU_EXCHANGED = const(21)
_IRQ_L2CAP_ACCEPT = const(22)
_IRQ_L2CAP_CONNECT = const(23)
_IRQ_L2CAP_DISCONNECT = const(24)
_IRQ_L2CAP_RECV = const(25)
_IRQ_L2CAP_SEND_READY = const(26)
_IRQ_CONNECTION_UPDATE = const(27)
_IRQ_ENCRYPTION_UPDATE = const(28)
_IRQ_GET_SECRET = const(29)
_IRQ_SET_SECRET = const(30)

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
    def scan_and_connect(self):
        self.bt.gap_scan(20000, 30000, 30000)  # scan for 20 seconds

    def bt_irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            if self.uuid in adv_data:
                self.bt.gap_connect(addr_type, addr)
        elif event == _IRQ_SCAN_DONE:
            print("Scan complete")
        elif event == _IRQ_PERIPHERAL_CONNECT:
            # A successful gap_connect().
            conn_handle, addr_type, addr = data
            self.connected_nodes.append((conn_handle, addr))
        elif event == _IRQ_PERIPHERAL_DISCONNECT:
            # Connected peripheral has disconnected.
            conn_handle, addr_type, addr = data
            self.connected_nodes.remove((conn_handle, addr))
        elif event == _IRQ_GATTS_WRITE:
            # A client has written to this characteristic or descriptor.
            conn_handle, attr_handle = data
            self.buffer += self.bt.gatts_read(attr_handle)


    def advertise(self):
        adv_data = bytearray([
            0x02, 0x01, 0x06,  # Flags
            0x11, 0x07  # 128-bit UUID
        ]) + self.uuid
        # uuid_bytes = bytes.fromhex(self.uuid.decode('utf-8'))
        # adv_payload = b'\x02\x01\x06\x11\x06' + uuid_bytes
        self.bt.gap_advertise(100, adv_data)

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

        # self.bt_node.advertise()
        self.bt_node.scan_and_connect()
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
