import { iot, mqtt, auth } from "aws-iot-device-sdk-v2";
import dotenv from "dotenv";
import { createClient } from "@supabase/supabase-js";
dotenv.config();

// supabase config
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_API_KEY = process.env.SUPABASE_API_KEY;

// MQTT settings
const ENDPOINT = process.env.MQTT_HOST;
const REGION = "ap-southeast-1";
const CLIENT_ID = `FIRE-CLOUD`;
const SENSOR_DATA_TOPIC = "greendot/sensor/data";
const TIMEZONE_OFFSET = 8;

if (!SUPABASE_URL || !SUPABASE_API_KEY) {
    console.error("Missing SUPABASE_URL or SUPABASE_API_KEY environment variable");
    process.exit(1);
}
if (!ENDPOINT) {
    console.error("Missing MQTT_HOST environment variable");
    process.exit(1);
}
if (!process.env.AWS_ACCESS_KEY_ID || !process.env.AWS_SECRET_ACCESS_KEY) {
    console.error("Missing AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY environment variable");
    process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SUPABASE_API_KEY);

function convertEpochToUTC(epochTime) {
    const date = new Date(epochTime * 1000);
    return date.toISOString();
}

function establishConnection() {
    const configBuilder = iot.AwsIotMqttConnectionConfigBuilder.new_with_websockets({
        region: REGION,
        credentials_provider: auth.AwsCredentialsProvider.newDefault(),
    });

    configBuilder.with_clean_session(false);
    configBuilder.with_client_id(CLIENT_ID);
    configBuilder.with_endpoint(ENDPOINT);

    const config = configBuilder.build();
    const client = new mqtt.MqttClient();
    return client.new_connection(config);
}

async function connectAndSubscribe() {
    console.log("Connecting to AWS IoT Core...");
    await connection.connect();
    console.log("Connected to AWS IoT Core");
    // Subscribe to a topic
    await connection.subscribe(SENSOR_DATA_TOPIC, mqtt.QoS.AtLeastOnce, async (topic, payload) => {
        const messageBuffer = Buffer.from(payload);
        const messageString = messageBuffer.toString();
        const messageJson = JSON.parse(messageString);
        console.log(`Message received on ${topic}:`, messageJson);

        const temperature = messageJson.temp;
        const humidity = messageJson.humidity;
        const air_quality_ppm = messageJson.air;
        const flame_sensor_value = messageJson.flame;

        const flameProbability = getFireProbability({
            temp: temperature,
            humidity: humidity,
            airQuality: air_quality_ppm,
            flameValue: flame_sensor_value,
        });

        let { error } = await supabase.from("firecloud").insert({
            node_id: messageJson.id,
            timestamp: convertEpochToUTC(messageJson.timestamp),
            temperature: temperature,
            humidity: humidity,
            air_quality_ppm: air_quality_ppm,
            flame_sensor_value: flame_sensor_value,
            flame_probability: flameProbability, //TODO: insert the probability here (create a col on supabase first)
            //TODO: insert the r_value here as well (create in supabase first)
        });

        //TODO: after inserting, publish to update flame probability on mqtt
        if (error) {
            console.error(error);
            return;
        }
        console.log("Inserted into supabase");
    });
}

async function publishMessage(topic, message) {
    const messageJson = JSON.stringify(message);
    const messageBuffer = Buffer.from(messageJson);
    try {
        await connection.publish(topic, messageBuffer, mqtt.QoS.AtLeastOnce);
    } catch (e) {
        console.error("Error publishing message:", e);
    }
}

function getFireProbability({ temp, humidity, airQuality, flameValue }) {
    const p_flame = flameValue; //flame is either 1 or 0
    const p_air = null;
    const p_temp = getTempProbability(temp);
    const p_r_value = getRValueProbability(temp, humidity);
}

/* calculate r value based on temp and humidity */
function getRValueProbability(temp, humidity) {}
function getAirQualityProbability(airQuality) {}
function getTempProbability(temp) {
    const tempThreshold = 40; //highest in sg: 37 + 3 = 40 deg (3 for threshold)

    if (temp > tempThreshold) {
        return 1;
    } else {
        return 0;
    }
}

const connection = establishConnection();
connectAndSubscribe().catch((err) => {
    console.error("Error connecting to AWS IoT Core:", err);
    process.exit(1);
});
