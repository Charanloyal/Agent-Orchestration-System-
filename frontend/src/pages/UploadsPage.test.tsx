import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Outlet } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "../api/types";
import { renderRoutes } from "../test/utils";
import { UploadsPage } from "./UploadsPage";

const WS = "11111111-1111-1111-1111-111111111111";
const me: Me = {
  user_id: "u1", email: "a@example.test", display_name: "Ana", csrf_token: "csrf",
  memberships: [{ workspace_id: WS, workspace_name: "Team", role: "analyst" }],
};

const doc = {
  id: "d1", filename: "whitepaper.pdf", title: "Whitepaper", media_type: "application/pdf", size_bytes: 2048,
  sha256: "a".repeat(64), pages: 2, text_chars: 60, chunks: 2, uploaded_by: "Ana", uploaded_by_id: "u1",
  created_at: "2026-10-15T10:00:00Z",
};

describe("UploadsPage", () => {
  it("uploads a file as multipart with the CSRF token and shows rejections clearly", async () => {
    const requests: { method: string; body: unknown; headers: Record<string, string> }[] = [];
    const replies = [
      new Response(JSON.stringify([]), { status: 200 }),
      new Response(JSON.stringify({ error: { code: "unreadable_document", message: "Document rejected: encrypted pdf" } }), { status: 422 }),
      new Response(JSON.stringify(doc), { status: 201 }),
      new Response(JSON.stringify([doc]), { status: 200 }),
    ];
    vi.stubGlobal("fetch", vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ method: init?.method ?? "GET", body: init?.body, headers: init?.headers as Record<string, string> });
      return replies.shift()!;
    }));
    const { setCsrfToken } = await import("../api/client");
    setCsrfToken("csrf");

    renderRoutes([{ element: <Outlet context={me} />, children: [{ path: "w/:workspaceId/documents", element: <UploadsPage /> }] }],
                 `/w/${WS}/documents`);
    const user = userEvent.setup();
    expect(await screen.findByText("No documents yet")).toBeInTheDocument();

    const file = new File(["%PDF-1.4 ..."], "secret.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("Document file"), file);
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Document rejected: encrypted pdf");

    await user.upload(screen.getByLabelText("Document file"), new File(["%PDF-1.4"], "whitepaper.pdf"));
    await user.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText("Whitepaper")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete whitepaper.pdf" })).toBeInTheDocument();

    const post = requests.find((r) => r.method === "POST");
    expect(post?.body).toBeInstanceOf(FormData);
    expect(post?.headers["X-CSRF-Token"]).toBe("csrf");
    expect(post?.headers["Content-Type"]).toBeUndefined();
    setCsrfToken(null);
  });
});
