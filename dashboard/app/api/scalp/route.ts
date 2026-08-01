import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export const dynamic = "force-dynamic";

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
  const [state, backtest] = await Promise.all([
    readJson("scalp_state.json"),
    readJson("scalp_backtest.json"),
  ]);
  return NextResponse.json({ state, backtest });
}
