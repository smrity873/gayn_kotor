import "dotenv/config";
import { Files } from "files-sdk";
import { neon } from "files-sdk/neon";

async function main() {
  console.log("Connecting to Neon Object Storage bucket: uploads...");
  const files = new Files({ adapter: neon({ bucket: "uploads" }) });

  const testKey = "test-file.txt";
  const testContent = "Hello from Gayn Kotor - Neon Object Storage is verified!";

  console.log(`Uploading '${testKey}'...`);
  await files.upload(testKey, testContent, { contentType: "text/plain" });
  console.log("Upload successful!");

  console.log("Listing bucket contents:");
  const listResult = await files.list();
  console.log("Found objects:", JSON.stringify(listResult, null, 2));

  console.log(`Reading '${testKey}' back...`);
  const downloaded = await files.download(testKey);
  const text = await downloaded.text();
  console.log("Read back content:", text);

  if (text === testContent) {
    console.log("PROVE IT WORKS: Verified successfully!");
  } else {
    throw new Error("Content mismatch!");
  }
}

main().catch((err) => {
  console.error("Storage test failed:", err);
  process.exit(1);
});

