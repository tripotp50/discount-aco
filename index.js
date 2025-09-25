const { MongoClient } = require("mongodb");

// replace <db_password> with your real password
const uri = "mongodb+srv://tripotp5_db_user:<db_password>@aco.phoxbnu.mongodb.net/?retryWrites=true&w=majority&appName=ACO";

const client = new MongoClient(uri);

async function run() {
  try {
    await client.connect();
    console.log("✅ Connected successfully to MongoDB!");

    // Pick a database and collection
    const database = client.db("testdb"); // change "testdb" to your DB name
    const collection = database.collection("testcol");

    // Example insert
    const doc = { name: "Aaron", createdAt: new Date() };
    const result = await collection.insertOne(doc);
    console.log("Inserted document:", result.insertedId);

  } catch (err) {
    console.error("❌ Connection error:", err);
  } finally {
    await client.close();
  }
}

run();
