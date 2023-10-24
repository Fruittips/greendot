import machine
import network
import ubluetooth
import ustruct
import umqtt.simple
import time
import ubinascii
import urandom

class BTNode:
    def __init__(self):
        self.bt = ubluetooth.BLE()
        self.bt.active(True)
        self.bt.irq(self.bt_irq)
        self.connected_nodes = []
        self.buffer = b''
        self.uuid = self._generate_uuid()
        
    def _generate_uuid(self):
        random_bytes = urandom.urandom(16)  # Generate 16 random bytes
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
        self.dht_sensor = machine.ADC(machine.Pin(32))
        self.air_quality_sensor = machine.ADC(machine.Pin(35))
        self.flame_sensor = machine.ADC(machine.Pin(34))
        self.wifi = network.WLAN(network.STA_IF)
        self.wifi.active(True)
        self.mqtt_client = umqtt.simple.MQTTClient("node", "a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.coms")
        self.bt_node = BTNode()
    
    def connect_wifi(self):
        self.wifi.connect('skku', 'skku1398')
        while not self.wifi.isconnected():
            time.sleep(1)
        self.mqtt_client.connect()
    
    def read_sensors(self):
        return [sensor.read() for sensor in self.sensors]
    
    def send_data(self, data):
        self.mqtt_client.publish("fire/data", data)
    
    def start(self):
        self.connect_wifi()
        self.bt_node.advertise()
        while True:
            if self.wifi.isconnected():
                data = self.read_sensors()
                self.send_data(str(data))
                bt_message = self.bt_node.process_buffer()
                if bt_message:
                    self.send_data(bt_message)
            else:
                # Assume a simple function to send data to another node via Bluetooth
                for conn_handle, _ in self.bt_node.connected_nodes:
                    self.bt_node.send_data(conn_handle, str(self.read_sensors()))

node = Node()
node.start()
