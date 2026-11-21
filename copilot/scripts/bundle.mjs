// Bundles the compiled CLI (and the workspace packages and zod it uses) into one file, so the
// published package has no runtime dependencies. Run `npm run build` first (npm run bundle does).
import { chmodSync, readFileSync } from "node:fs";
import { build } from "esbuild";

const pkg = JSON.parse(readFileSync("packages/cli/package.json", "utf8"));
const outfile = "packages/cli/dist/copilot.js";

await build({
  entryPoints: ["packages/cli/dist/bin.js"],
  outfile,
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node22",
  legalComments: "none",
  define: { __VERSION__: JSON.stringify(pkg.version) },
});
chmodSync(outfile, 0o755);
console.log(`bundled ${outfile} (version ${pkg.version})`);
