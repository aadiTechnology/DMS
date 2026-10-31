// Builds dms-design-showcase.html by embedding the five template files into showcase.template.html.
// The templates stay the single source of truth: edit the JSON, then run `node design-showcase/build-showcase.mjs`.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { checkAll, ORDER } from "./check-templates.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const problems = checkAll(path.join(here, "templates"));
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
const templates = ORDER.map((key) => JSON.parse(fs.readFileSync(path.join(here, "templates", `${key}.json`), "utf8")));
const html = fs
  .readFileSync(path.join(here, "showcase.template.html"), "utf8")
  .replace("/*__TEMPLATES__*/null", JSON.stringify(templates).replace(/</g, "\\u003c"));
fs.writeFileSync(path.join(here, "dms-design-showcase.html"), html, "utf8");
console.log(`Wrote design-showcase/dms-design-showcase.html (${(html.length / 1024).toFixed(0)} KB, ${templates.length} designs)`);
