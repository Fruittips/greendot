import dht
import machine
import time
import mq135



#flame sensor
#1 = no flame
#0 = flame
flame_sensor = machine.Pin(4, machine.Pin.IN)
# print(flame_sensor.value())



#DHT22 humidity and temperature Sensor
d = dht.DHT22(machine.Pin(5, machine.Pin.IN))
# d.measure() #measure is required to call measure func
# temperature = d.temperature()
# humidity = d.humidity()
# print(temperature, humidity)


# #MQ135 Air quality sensor
mq = mq135.MQ135(machine.Pin(15, machine.Pin.IN))
# rzero = mq.get_rzero()
# resistance = mq.get_resistance()
# 
# 
# #MQ135 Corrected value with DHT22 humidty and temperature
# corrected_rzero = mq.get_corrected_rzero(temperature, humidity)
# corrected_resistance = mq.get_corrected_resistance(temperature, humidity)
# print(f"corrected_rzero = {corrected_rzero}, corrected_resistance = {corrected_resistance}")

x = 0
while x <300:
    x = x + 1
    d.measure()
    temperature = d.temperature()
    humidity = d.humidity()
#     print(f"temperature = {temperature},humidity = {humidity} ")
    corrected_ppm = mq.get_corrected_ppm(temperature,humidity)
    print(f"corrected_ppm = {corrected_ppm}, temperature = {temperature}, humidity = {humidity}, flame_sensor.value() = {flame_sensor.value()}")
    time.sleep(1)
    



