import os,time,ujson,machine,network
from HC_SR04 import HCSR04
import ssd1306
from umqtt.simple import MQTTClient


#Init display
i2c = machine.SoftI2C(sda=machine.Pin(4), scl=machine.Pin(5))
display = ssd1306.SSD1306_I2C(128, 64, i2c)
# Clear any initial display
display.fill(0)
display.show()

#Init PIR
# motion = False
# def handle_interrupt(pin):
#     global motion
#     global interrupt_pin
#     motion = True
#     interrupt_pin = pin
#     
# pir = machine.Pin(2, machine.Pin.IN)
# pir.irq(trigger = machine.Pin.IRQ_RISING, handler = handle_interrupt)
# led = machine.Pin(5, machine.Pin.OUT)
# led.value(0)


# Init Ultrasonic Sensor
sensor = HCSR04(trigger_pin=5, echo_pin=18, echo_timeout_us=10000)
led_red = machine.Pin(22,machine.Pin.OUT, value=0)
led_green = machine.Pin(21,machine.Pin.OUT, value=0)

# wifi SSID & Password
wifi_ssid = "Bon"
wifi_password = "Huhuhu123"

#Enter your AWS IoT endpoint. You can find it in the Settings page of
#your AWS IoT Core console. 
#https://docs.aws.amazon.com/iot/latest/developerguide/iot-connect-devices.html 
aws_endpoint = b'a3dhth9kymg9gk-ats.iot.ap-southeast-1.amazonaws.com'

#If you followed the blog, these names are already set.
thing_name = "Esp32"
client_id = "iotconsole-9d7ccd0d-27b9-44c0-86f6-9ce17ca94e74"
private_key = "49b64d36ce482bfda15afd6177c4d89b058434dc61e15f742d2bc56d0a9ec493.key"
private_cert = "49b64d36ce482bfda15afd6177c4d89b058434dc61e15f742d2bc56d0a9ec493.crt"

#Read the files used to authenticate to AWS IoT Core
with open(private_key, 'r') as f:
    key = f.read()
with open(private_cert, 'r') as f:
    cert = f.read()

#These are the topics we will subscribe to. We will publish updates to /update.
#We will subscribe to the /update/delta topic to look for changes in the device shadow.
topic_pub = "$aws/things/" + thing_name + "/hotspot"
topic_sub = "$aws/things/" + thing_name + "/hotspot"
ssl_params = {"key":key, "cert":cert, "server_side":False}

#Connect to the wireless network
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
if not wlan.isconnected():
    print('Connecting to network...')
    wlan.connect(wifi_ssid, wifi_password)
    while not wlan.isconnected():
        pass

    print('Connection successful')
    print('Network config:', wlan.ifconfig())


def mqtt_connect(client=client_id, endpoint=aws_endpoint, sslp=ssl_params):
    mqtt = MQTTClient(client_id=client, server=endpoint, port=8883, keepalive=1200, ssl=True, ssl_params=sslp)
    print("Connecting to AWS IoT...")
    mqtt.connect()
    print("Done")
    return mqtt

def mqtt_publish(client, topic, message=''):
    print("Publishing message...")
    client.publish(topic, message)
    print(message)

def mqtt_subscribe(topic, msg):
    print("Message received...")
    message = ujson.loads(msg)
    if message["lot"] == "occupied":
        led_red.value(1)
        led_green.value(0)
    else:
        led_red.value(0)
        led_green.value(1)
#     print(topic, message)
#     print("Done")



#We use our helper function to connect to AWS IoT Core.
#The callback function mqtt_subscribe is what will be called if we 
#get a new message on topic_sub.
try:
    mqtt = mqtt_connect()
    mqtt.set_callback(mqtt_subscribe)
    mqtt.subscribe("hotspot")
    
except Exception as e:
    print("Unable to connect to MQTT.")
    print(f"Exception = {e}")
     

x = 0
display.text("Car Lot 1",0,0,1)
display.show()
while x<100:
    x = x + 1
    display.fill_rect(0,14,128,50,0) #reset display
    display.fill_rect(0,28,128,50,0) #reset display
    if sensor.distance_cm() > 10:
        payload_empty = {"lot":"empty"}
        display.text("Empty",0,14,1)
        display.text(str(x),0,28,1)
        display.show()
        try:
            mqtt_publish(client=mqtt,topic="hotspot", message=ujson.dumps(payload_empty))
        except Exception as e:
            print("Unable to publish message.")
            print(f"error = {e}")
    else:
        payload_occupied = {"lot":"occupied"}
        display.text("Occupied",0,14,1)
        display.text(str(x),0,28,1)
        display.show()
        try:
            mqtt_publish(client=mqtt,topic="hotspot", message=ujson.dumps(payload_occupied))
        except Exception as e:
            print("Unable to publish message.")
            print(f"error = {e}")
    
    try:
        msg = mqtt.check_msg()
    except Exception as e:
        print("Unable to check for messages.")
    time.sleep(3)






while True:
#Check for messages.
    try:
        mqtt.check_msg()
    except:
        print("Unable to check for messages.")

    mesg = ujson.dumps({
        "state":{
            "reported": {
                "device": {
                    "client": client_id,
                    "uptime": time.ticks_ms(),
                    "hardware": info[0],
                    "firmware": info[2]
                },
                "sensors": {
                    "light": light_sensor.read()
                },
                "led": {
                    "onboard": led.value()
                }
            }
        }
    })

#Using the message above, the device shadow is updated.
    try:
        mqtt_publish(client=mqtt, message=mesg)
    except:
        print("Unable to publish message.")

#Wait for 10 seconds before checking for messages and publishing a new update.
    print("Sleep for 10 seconds")
    time.sleep(1000)