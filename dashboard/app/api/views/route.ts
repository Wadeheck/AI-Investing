import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export const dynamic = "force-dynamic";

function viewsPath(): string {
  return process.env.VIEWS_PATH || path.join(process.cwd(), "..", "data", "views.json");
}

const DEFAULTS = { decisiveness: 0.7, risk_appetite: 0.5, stance: "normal", views: {}, blocklist: [] as string[], focus: [] as string[] };

export async function GET() {
  try {
    const raw = await fs.readFile(viewsPath(), "utf-8");
    return NextResponse.json({ ...DEFAULTS, ...JSON.parse(raw) });
  } catch {
    return NextResponse.json(DEFAULTS);
  }
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const clean = {
    decisiveness: Math.max(0, Math.min(1, Number(body.decisiveness ?? 0.7))),
    risk_appetite: Math.max(0, Math.min(1, Number(body.risk_appetite ?? 0.5))),
    stance: String(body.stance ?? "normal"),
    views:
      body.views && typeof body.views === "object"
        ? Object.fromEntries(
            Object.entries(body.views).map(([k, v]) => [String(k).toUpperCase(), Math.max(-1, Math.min(1, Number(v)))])
          )
        : {},
    blocklist: Array.isArray(body.blocklist) ? body.blocklist.map((s: unknown) => String(s).toUpperCase()) : [],
    focus: Array.isArray(body.focus) ? body.focus.map((s: unknown) => String(s).toUpperCase()) : [],
  };
  const p = viewsPath();
  await fs.mkdir(path.dirname(p), { recursive: true });
  await fs.writeFile(p, JSON.stringify(clean, null, 2));
  return NextResponse.json({ ok: true, views: clean });
}
