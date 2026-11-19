import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildFrontend } from "../frontend/build.mjs";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
buildFrontend(join(root, "dist"));
