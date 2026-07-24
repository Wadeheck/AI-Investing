import { NextRequest, NextResponse } from "next/server";

// HTTP Basic Auth, gated on DASHBOARD_USER/DASHBOARD_PASSWORD being set.
// Unset (the default) = no auth, matching the "works with zero config"
// philosophy everywhere else in this repo. Set both once you run this
// anywhere reachable off localhost.

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function unauthorized(): NextResponse {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="AI-Investing Dashboard"' },
  });
}

export function middleware(req: NextRequest) {
  const user = process.env.DASHBOARD_USER;
  const pass = process.env.DASHBOARD_PASSWORD;
  if (!user || !pass) return NextResponse.next();

  const header = req.headers.get("authorization");
  if (!header?.startsWith("Basic ")) return unauthorized();

  let decoded = "";
  try {
    decoded = atob(header.slice(6));
  } catch {
    return unauthorized();
  }
  const sep = decoded.indexOf(":");
  const gotUser = sep === -1 ? decoded : decoded.slice(0, sep);
  const gotPass = sep === -1 ? "" : decoded.slice(sep + 1);

  if (timingSafeEqual(gotUser, user) && timingSafeEqual(gotPass, pass)) {
    return NextResponse.next();
  }
  return unauthorized();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
