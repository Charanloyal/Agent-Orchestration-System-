export type HealthResponse = {
  status: string;
};

function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { status?: unknown }).status === "string"
  );
}

export async function fetchHealth(signal: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/health", {
    signal,
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`Backend responded with HTTP ${response.status}.`);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new Error("Backend response was not valid JSON.");
  }

  if (!isHealthResponse(body)) {
    throw new Error("Backend returned an unexpected health payload.");
  }

  return body;
}
