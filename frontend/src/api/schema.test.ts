// @vitest-environment node
/// <reference types="node" />
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, expectTypeOf, it } from "vitest";

import type { components, operations } from "./schema";

const frontendRoot = path.resolve(import.meta.dirname, "../..");
const contractPath = path.resolve(frontendRoot, "../api/openapi.yaml");
const schemaPath = path.resolve(frontendRoot, "src/api/schema.d.ts");
const cli = path.resolve(frontendRoot, "node_modules/openapi-typescript/bin/cli.js");

/** The arguments `npm run <name>` passes to openapi-typescript. */
function scriptArgs(name: string): string[] {
  const pkg = JSON.parse(readFileSync(path.join(frontendRoot, "package.json"), "utf8"));
  const [command, ...args] = (pkg.scripts[name] as string).split(" ");
  expect(command).toBe("openapi-typescript");
  return args;
}

function runCli(args: string[], cwd: string) {
  return spawnSync(process.execPath, [cli, ...args], { cwd, encoding: "utf8" });
}

// Each case spawns openapi-typescript, which takes a few seconds.
describe("generated API types", { timeout: 30_000 }, () => {
  let tmp: string | undefined;

  afterEach(() => {
    if (tmp) rmSync(tmp, { recursive: true, force: true });
    tmp = undefined;
  });

  it("gen-types and check-types read the contract and write src/api/schema.d.ts", () => {
    expect(scriptArgs("gen-types")).toEqual(["../api/openapi.yaml", "-o", "src/api/schema.d.ts"]);
    expect(scriptArgs("check-types")).toEqual([...scriptArgs("gen-types"), "--check"]);
  });

  it("check-types passes when the committed file matches the contract", () => {
    const result = runCli(scriptArgs("check-types"), frontendRoot);
    expect(result.status, result.stderr).toBe(0);
  });

  it("check-types fails when a schema field changes without regenerating", () => {
    tmp = mkdtempSync(path.join(tmpdir(), "check-types-"));
    copyFileSync(schemaPath, path.join(tmp, "schema.d.ts"));
    const contract = readFileSync(contractPath, "utf8");
    const args = ["openapi.yaml", "-o", "schema.d.ts", "--check"];

    writeFileSync(path.join(tmp, "openapi.yaml"), contract);
    expect(runCli(args, tmp).status).toBe(0);

    const edited = contract.replace(/^( +)country_name:$/m, "$1country_label:");
    expect(edited).not.toBe(contract);
    writeFileSync(path.join(tmp, "openapi.yaml"), edited);
    expect(runCli(args, tmp).status).not.toBe(0);
  });
});

// The checks below are on types, so `tsc -b` in `npm run build` enforces them.
type Json<R> = R extends { content: { "application/json": infer B } } ? B : never;
type Responses<Op extends keyof operations> = operations[Op]["responses"];
type ErrorBody = components["schemas"]["Error"];

describe("contract conventions in the generated types", () => {
  it("every response that returns data has data_mode", () => {
    type DataMode = "demo" | "live";
    expectTypeOf<components["schemas"]["DataMode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"listCountries">[200]>["data_mode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"listIndicators">[200]>["data_mode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"getCoverage">[200]>["data_mode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"runInvestigation">[200]>["data_mode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"listInvestigations">[200]>["data_mode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"saveInvestigation">[201]>["data_mode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"getInvestigation">[200]>["data_mode"]>().toEqualTypeOf<DataMode>();
    expectTypeOf<Json<Responses<"updateInvestigation">[200]>["data_mode"]>().toEqualTypeOf<DataMode>();
  });

  it("every /api operation returns the shared error schema for 503", () => {
    expectTypeOf<Json<Responses<"listCountries">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"listIndicators">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"getCoverage">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"runInvestigation">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"listInvestigations">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"saveInvestigation">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"getInvestigation">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"updateInvestigation">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<Json<Responses<"exportInvestigationPdf">[503]>>().toEqualTypeOf<ErrorBody>();
    expectTypeOf<ErrorBody["service"]>().toEqualTypeOf<"gemini" | "data_service" | "database" | null>();
  });

  it("missing values are null, and the PDF export is application/pdf", () => {
    expectTypeOf<components["schemas"]["NumericResult"]["value"]>().toEqualTypeOf<number | null>();
    expectTypeOf<components["schemas"]["SeriesPoint"]["value"]>().toEqualTypeOf<number | null>();
    expectTypeOf<
      Responses<"exportInvestigationPdf">[200]["content"]
    >().toEqualTypeOf<{ "application/pdf": string }>();
  });
});
