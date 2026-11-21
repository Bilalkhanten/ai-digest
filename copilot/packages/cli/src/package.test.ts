import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), "utf8"));
const cli = read("../package.json");
const root = read("../../../package.json");

// The published package is what other people install, so its metadata is worth pinning.
describe("published package metadata", () => {
  it("is a public, scoped package under the owner's name with a single bin", () => {
    expect(cli.private).not.toBe(true);
    expect(cli.name).toBe("@bilalkhanten/incident-copilot");
    expect(cli.bin).toEqual({ copilot: "dist/copilot.js" });
    expect(cli.files).toEqual(["dist/copilot.js"]);
  });

  it("publishes to GitHub Packages and links back to the repository", () => {
    expect(cli.publishConfig.registry).toBe("https://npm.pkg.github.com");
    expect(cli.repository.url).toContain("github.com/Bilalkhanten/ai-digest");
    expect(cli.repository.directory).toBe("copilot/packages/cli");
  });

  it("is MIT licensed and ships its license file", () => {
    expect(cli.license).toBe("MIT");
    expect(root.license).toBe("MIT");
    const text = readFileSync(new URL("../LICENSE", import.meta.url), "utf8");
    expect(text.startsWith("MIT License")).toBe(true);
    expect(text).toContain("Bilalkhanten");
  });

  it("has no runtime dependencies, because everything is bundled", () => {
    expect(cli.dependencies).toBeUndefined();
  });

  it("keeps the workspace root private so it can never be published by accident", () => {
    expect(root.private).toBe(true);
  });

  it("builds the version into the bundle from this package.json", () => {
    expect(cli.version).toMatch(/^\d+\.\d+\.\d+$/);
  });
});
