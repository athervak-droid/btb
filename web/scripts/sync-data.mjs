// Copy the freshly built leaderboard into the app's committed snapshot.
// Run from web/:  npm run sync
// Source is the repo's results/leaderboard.json (produced by scripts/leaderboard.py).
import { copyFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../results/leaderboard.json");
const dest = resolve(here, "../data/leaderboard.json");

if (!existsSync(src)) {
  console.error(`No leaderboard at ${src}. Build it first:`);
  console.error("  python scripts/leaderboard.py --results results/ --out results/leaderboard.json");
  process.exit(1);
}
copyFileSync(src, dest);
console.log(`synced ${src} -> ${dest}`);
