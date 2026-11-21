#!/usr/bin/env node
import { main } from "./main.js";

// Kept separate from main.ts so the "run it" decision never depends on how the file was invoked
// (npm installs the command as a symlink with a different name).
main(process.argv.slice(2), {
  out: (text) => process.stdout.write(text),
  err: (text) => process.stderr.write(text),
}).then((code) => process.exit(code));
