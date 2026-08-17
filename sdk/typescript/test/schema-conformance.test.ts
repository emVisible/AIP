/**
 * Schema conformance: validates the schema-kind fixtures from
 * conformance/tests/*.json against schema/aip.json (the SAME fixtures the
 * Python runner uses) — cross-language conformance for the Kernel.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import AjvModule from "ajv";

// ajv publishes CJS types via `export =`; the ESM default binding is the
// Ajv class at runtime, but TS types it as a namespace under NodeNext.
const Ajv = AjvModule as unknown as new (options?: { strict?: boolean }) => {
  addSchema(schema: unknown, key: string): void;
  validate(key: string, data: unknown): boolean;
};

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..", "..", "..");

const schemaPath = path.join(repo, "schema", "aip.json");
const testsDir = path.join(repo, "conformance", "tests");

const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
const ajv = new Ajv({ strict: false });
ajv.addSchema(schema, "aip");

const TYPES = ["event", "action", "result", "error"];
const REQUIRED = ["v", "type", "id", "session", "seq", "source", "payload"];

function classifyInvalid(msg: unknown): string {
  if (typeof msg !== "object" || msg === null) return "INVALID_MESSAGE";
  const m = msg as Record<string, unknown>;
  if (m.v !== 1) return "UNSUPPORTED_VERSION";
  if (!TYPES.includes(m.type as string)) return "INVALID_MESSAGE";
  for (const f of REQUIRED) {
    if (m[f] === undefined || m[f] === null || m[f] === "") return "INVALID_MESSAGE";
  }
  return "INVALID_MESSAGE";
}

function casesOf(test: any): Array<{ input: unknown; expect: any }> {
  if (test.cases) return test.cases;
  return [{ input: test.input, expect: test.expect }];
}

test("schema fixtures validate identically to the Python runner", () => {
  let total = 0;
  let passed = 0;

  for (const file of readdirSync(testsDir).filter((f) => f.endsWith(".json"))) {
    const group = JSON.parse(readFileSync(path.join(testsDir, file), "utf8"));
    for (const t of group.tests) {
      if (t.kind !== "schema") continue;
      for (const c of casesOf(t)) {
        total++;
        const valid = ajv.validate("aip", c.input);
        const expectValid = c.expect.valid;
        let ok = valid === expectValid;
        if (!valid && c.expect.error) {
          ok = classifyInvalid(c.input) === c.expect.error;
        }
        if (ok) passed++;
        else {
          assert.fail(
            `${t.id}: expected ${expectValid} (${c.expect.error ?? ""}), got ` +
              `${valid}${valid ? "" : " / " + classifyInvalid(c.input)} ` +
              `for ${JSON.stringify(c.input)}`,
          );
        }
      }
    }
  }

  assert.ok(passed > 0, "no schema fixtures found");
  // eslint-disable-next-line no-console
  console.log(`schema conformance: ${passed}/${total} passed`);
});