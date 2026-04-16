import { NextResponse, type NextRequest } from "next/server";

/**
 * Next.js Edge Middleware — redirect unauthenticated users to /login.
 *
 * We check for the presence of the "mdl_access_token" cookie or a token
 * sent via the Authorization header. Since localStorage is not available
 * in Edge middleware, the frontend also sets a lightweight cookie via
 * lib/auth.ts so middleware can read it.
 *
 * Public routes (no auth required): /login, /register, /_next, /favicon.ico, /api.
 */

const PUBLIC_PATHS = ["/login", "/register"];

function isPublicPath(pathname: string): boolean {
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) return true;
  if (pathname.startsWith("/_next")) return true;
  if (pathname.startsWith("/api")) return true;
  if (pathname === "/favicon.ico") return true;
  return false;
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // Check for token in cookie (set by lib/auth.ts alongside localStorage)
  const token =
    request.cookies.get("mdl_access_token")?.value ??
    request.headers.get("authorization")?.replace("Bearer ", "");

  if (!token) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all paths except static files and images.
     */
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
