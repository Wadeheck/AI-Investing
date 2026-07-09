import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export const dynamic = "force-dynamic";

// The engine writes JSON into <repo>/data. Running `next dev` from dashboard/ puts
// cwd at dashboard/, so ../data resolves to the engine's output. Override with DATA_DIR.
function dataDir(): string {
  return process.env.DATA_DIR || path.join(process.cwd(), "..", "data");
}

async function readJson(name: string): Promise<unknown | null> {
  try {
    const raw = await fs.readFile(path.join(dataDir(), name), "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function GET() {
  const [state, history, backtest] = await Promise.all([
    readJson("state.json"),
    readJson("history.json"),
    readJson("backtest.json"),
  ]);
  return NextResponse.json({ state, history, backtest });
}
