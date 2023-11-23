import dht
import machine
import mq135

class SensorsManager:
    def __init__(self, flame_pin, temp_humidity_pin, air_pin):
        print("Initialising sensors manager...")
        self.flame_sensor = machine.Pin(flame_pin, machine.Pin.IN)
        self.temp_humidity_sensor = dht.DHT22(machine.Pin(temp_humidity_pin, machine.Pin.IN))
        self.air_sensor = mq135.MQ135(machine.Pin(air_pin, machine.Pin.IN))
        print("Initialised sensors manager")
    
    def get_flame_presence(self):
        raw_value = self.flame_sensor.value()
        if (raw_value == 0):
            return 1
        if (raw_value == 1):
            return 0
    
    def get_temp_humidity(self):
        try:
            self.temp_humidity_sensor.measure()
            temp = self.temp_humidity_sensor.temperature()
            humidity = self.temp_humidity_sensor.humidity()
            return temp , humidity
        except Exception as e:
            print("Error getting temperature and humidity:", e)
            return None, None
    
    def get_air_quality(self, temperature, humidity):
        return self.air_sensor.get_corrected_ppm(temperature, humidity)