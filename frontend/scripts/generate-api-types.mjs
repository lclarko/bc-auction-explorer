import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const scriptDirectory = fileURLToPath(new URL(".", import.meta.url));
const schemaPath = new URL("../src/api/schema.json", `file://${scriptDirectory}`).pathname;
const outputPath = new URL("../src/api/types.ts", `file://${scriptDirectory}`).pathname;
const schema = JSON.parse(await readFile(schemaPath, "utf8"));
const ast = await openapiTS(schema, { exportType: true });

await writeFile(outputPath, astToString(ast), "utf8");
