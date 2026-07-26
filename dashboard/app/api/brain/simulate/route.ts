import { NextResponse } from "next/server";
import { execFile } from "child_process";
import path from "path";

export const dynamic = "force-dynamic";

// Runs the engine's brain on one hypothetical headline and returns the ripple.
// The CLI prints pure JSON on stdout (see main.py --brain-simulate).
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const headline = String(body.headline ?? "").slice(0, 300).trim();
  if (!headline) {
    return NextResponse.json({ error: "headline required" }, { status: 400 });
  }
  const engineDir = process.env.ENGINE_DIR || path.join(process.cwd(), "..", "engine");
  const python = process.env.PYTHON_BIN || "python3";

  const result = await new Promise<{ ok: boolean; out?: string; err?: string }>((resolve) => {
    execFile(
      python,
      ["-m", "ai_investing.main", "--brain-simulate", headline],
      { cwd: engineDir, timeout: 90_000, maxBuffer: 8 * 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) resolve({ ok: false, err: stderr || error.message });
        else resolve({ ok: true, out: stdout });
      }
    );
  });

  if (!result.ok) {
    return NextResponse.json({ error: `simulation failed: ${result.err}` }, { status: 500 });
  }
  try {
    // stdout may carry stray lines (e.g. dotenv warnings) — parse the last JSON line
    const lines = (result.out || "").trim().split("\n");
    const jsonLine = lines.reverse().find((l) => l.trim().startsWith("{"));
    return NextResponse.json(JSON.parse(jsonLine || "{}"));
  } catch {
    return NextResponse.json({ error: "could not parse engine output" }, { status: 500 });
  }
}
