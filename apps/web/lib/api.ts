import { getApiBase } from "./api-url";

export async function fetchJSON<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const base = getApiBase();
  const res = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadFile(
  path: string,
  file: File,
  extraFields?: Record<string, string>
): Promise<unknown> {
  const base = getApiBase();
  const form = new FormData();
  form.append("file", file);
  if (extraFields) {
    Object.entries(extraFields).forEach(([k, v]) => form.append(k, v));
  }
  const res = await fetch(`${base}${path}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`Upload ${res.status}: ${text}`);
  }
  return res.json();
}

export function streamSSE(
  path: string,
  onMessage: (data: Record<string, unknown>) => void,
  onError?: (err: Event) => void
): EventSource {
  const base = getApiBase();
  const url = `${base}${path}`;
  const es = new EventSource(url);
  es.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      onMessage(parsed);
    } catch {
      // skip non-JSON messages
    }
  };
  es.onerror = (err) => {
    if (onError) onError(err);
    es.close();
  };
  return es;
}
