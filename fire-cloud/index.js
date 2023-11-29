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
const FLAME_PRESENCE_TOPIC = "greendot/status";

/* e.g. node id 1 has status 0 */
const fireStatuses = {
    0: 0,
    1: 0,
};

/* e.g. node id 1 has null noFireDuration */
const noFireDurations = {
    0: null,
    1: null,
};

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

    // Subscribe to a topic
    await connection.subscribe(SENSOR_DATA_TOPIC, mqtt.QoS.AtLeastOnce, async (topic, payload) => {
        const messageBuffer = Buffer.from(payload);
        const messageString = messageBuffer.toString();
        const messageJson = JSON.parse(messageString);
        console.log(`Message received on ${topic}:`, messageJson);

        const nodeId = messageJson.id;
        const temperature = messageJson.temp;
        const humidity = messageJson.humidity;
        const airQualityPpm = messageJson.air;
        const flameSensorValue = messageJson.flame;
        const utcTimestamp = convertEpochToUTC(messageJson.timestamp);

        const { data, error } = await supabase
            .from("firecloud")
            .insert({
                node_id: messageJson.id,
                timestamp: utcTimestamp,
                temperature: temperature,
                humidity: humidity,
                air_quality_ppm: airQualityPpm,
                flame_sensor_value: flameSensorValue,
            })
            .select();
        if (error) {
            console.error(error);
            return;
        }

        //invoke lambda function to calculate fire probability and update database
        const rowId = data[0].id;
        const lambdaRes = await invokeAnalytics(
            nodeId,
            rowId,
            temperature,
            flameSensorValue,
            utcTimestamp
        );

        const fireProbability = lambdaRes.fire_probability;

        if (fireProbability === null) {
            console.log("lambda function failed to calculate fire probability");
            return;
        }
        await validateAndPublishFireMessage(nodeId, fireProbability);
    });
}

// fire status 0 = no fire, 1 = fire
async function validateAndPublishFireMessage(nodeId, fireProbability) {
    const fireProbabilityThreshold = 0.3;

    if (fireProbability > fireProbabilityThreshold) {
        if (fireStatuses[nodeId] === 0) await updateAndPublishFireMessage(FLAME_PRESENCE_TOPIC, 1);
        fireStatuses[nodeId] = 1;
    }

    //if fire is dying down
    if (fireStatuses[nodeId] === 1) {
        if (fireProbability < fireProbabilityThreshold) {
            if (noFireDurations[nodeId] === null) {
                noFireDurations[nodeId] = new Date().getTime();
            } else {
                const currentTime = new Date().getTime();
                const timeDiff = currentTime - noFireDurations[nodeId];
                const timeDiffInMinutes = timeDiff / 60000;

                // if status has been 0 for more than 5 minutes -> there is no more fire -> publish status 0
                if (timeDiffInMinutes > 5) {
                    await updateAndPublishFireMessage(FLAME_PRESENCE_TOPIC, 0);
                    fireStatuses[nodeId] = 0;
                    noFireDurations[nodeId] = null;
                }
            }
        } else {
            noFireDurations[nodeId] = null;
        }
    }
}

async function updateAndPublishFireMessage(topic, status) {
    const hasFire = status === 1;
    const { error } = await supabase
        .from("fire_status")
        .update({ has_fire: hasFire, timestamp: new Date().toISOString() })
        .eq("id", 1);
    if (error) {
        console.error(error);
        return;
    }

    await publishMessage(topic, { status: status });
}

async function publishMessage(topic, message) {
    const messageJson = JSON.stringify(message);
    const messageBuffer = Buffer.from(messageJson);
    try {
        console.log(`Publishing message to ${topic}:`, messageJson);
        await connection.publish(topic, messageBuffer, mqtt.QoS.AtLeastOnce);
    } catch (e) {
        console.error("Error publishing message:", e);
    }
}

// Function to invoke the Analytics lambda function to calculate the fire probability and update the database
async function invokeAnalytics(nodeId, rowId, temp, flameValue, utcDatetime) {
    console.log("Invoking lambda function...");
    const command = new InvokeCommand({
        FunctionName: "greendot-analytics",
        InvocationType: "RequestResponse",
        Payload: JSON.stringify({
            nodeId: nodeId,
            rowId: rowId,
            temp: temp,
            flame: flameValue,
            utc_datetime_string: utcDatetime,
        }),
    });

    const { Payload } = await lambdaClient.send(command);
    let result = Buffer.from(Payload).toString();
    result = JSON.parse(result);
    return JSON.parse(result.body);
}

const connection = establishConnection();
connectAndSubscribe().catch((err) => {
    console.error("Error connecting to AWS IoT Core:", err);
    process.exit(1);
});
