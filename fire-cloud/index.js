import { iot, mqtt, auth } from "aws-iot-device-sdk-v2";
import { LambdaClient, InvokeCommand } from "@aws-sdk/client-lambda";
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

if (!process.env.AWS_LAMBDA_KEY || !process.env.AWS_LAMBDA_SECRET) {
    console.error("Missing AWS_LAMBDA_KEY or AWS_LAMBDA_SECRET environment variable");
    process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SUPABASE_API_KEY);
const lambdaClient = new LambdaClient({
    region: REGION,
    credentials: {
        accessKeyId: process.env.AWS_LAMBDA_KEY,
        secretAccessKey: process.env.AWS_LAMBDA_SECRET,
    },
});

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
    // const result = await invokeAnalytics(1, 2, 3, 4); //TODO: remove this

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

        const { data, error } = await supabase
            .from("firecloud")
            .insert({
                node_id: messageJson.id,
                timestamp: convertEpochToUTC(messageJson.timestamp),
                temperature: temperature,
                humidity: humidity,
                air_quality_ppm: air_quality_ppm,
                flame_sensor_value: flame_sensor_value,
            })
            .select();
        if (error) {
            console.error(error);
            return;
        }
        console.log("Inserted into supabase");

        //TODO: invoke lambda function to calculate fire probability and update database
    });
}

//TODO: subscribe to supabase table for updates on the flag and timestamp -> validate and publish to MQTT topic
async function subscribeSupabase() {
    const { data, error } = await supabase
        .from("firecloud")
        .on("*", (payload) => {
            console.log("Change received!", payload);
        })
        .subscribe();
    if (error) {
        console.error(error);
        return;
    }
    console.log("Subscribed to supabase");
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

// Function to invoke the Analytics lambda function to calculate the fire probability and update the database
// TODO: rmb to pass row id of newly inserted row to lambda
async function invokeAnalytics(temp, humidity, airQuality, flameValue) {
    console.log("Invoking lambda function...");
    const command = new InvokeCommand({
        FunctionName: "greendot-analytics",
        Payload: JSON.stringify({
            temp: temp,
            humidity: humidity,
            airQuality: airQuality,
            flameValue: flameValue,
        }),
    });

    const { Payload } = await lambdaClient.send(command);
    const result = Buffer.from(Payload).toString();
    return JSON.parse(result).body;
}

const connection = establishConnection();
connectAndSubscribe().catch((err) => {
    console.error("Error connecting to AWS IoT Core:", err);
    process.exit(1);
});
