import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const schemaPath = fileURLToPath(new URL("../src/api/schema.json", import.meta.url));
const outputPath = fileURLToPath(new URL("../src/api/types.ts", import.meta.url));
const schema = JSON.parse(await readFile(schemaPath, "utf8"));
const ast = await openapiTS(schema, { exportType: true });

await writeFile(outputPath, astToString(ast), "utf8");
