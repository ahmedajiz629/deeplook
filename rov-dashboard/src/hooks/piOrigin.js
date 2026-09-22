export const PI_HOST = import.meta.env.VITE_PI_HOST || "deeplook.local";

export function servedFromPi() {
  const host = window.location.hostname;
  return (
    host === PI_HOST ||
    host.endsWith(".local") ||
    host === "localhost" ||
    host === "127.0.0.1"
  );
}

export function cameraSrc() {
  if (servedFromPi() && !import.meta.env.DEV) return "/video";
  return `http://${PI_HOST}/video`;
}

export function socketUrl() {
  if (servedFromPi() && !import.meta.env.DEV) {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/ws`;
  }
  return `ws://${PI_HOST}/ws`;
}
