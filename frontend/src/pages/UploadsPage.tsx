import { useRef, useState, type FormEvent } from "react";
import { useOutletContext, useParams } from "react-router";

import { useDeleteUpload, useUploadFile, useUploadSearch, useUploads } from "../api/hooks";
import type { Me } from "../api/types";
import { Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { formatDateTime } from "../format";

const formatSize = (bytes: number) =>
  bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;

export function UploadsPage() {
  const { workspaceId = "" } = useParams();
  const me = useOutletContext<Me>();
  const role = me.memberships.find((m) => m.workspace_id === workspaceId)?.role;
  const uploads = useUploads(workspaceId);
  const uploadFile = useUploadFile(workspaceId);
  const deleteUpload = useDeleteUpload(workspaceId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const search = useUploadSearch(workspaceId, submitted);
  const canUpload = role === "analyst" || role === "admin";

  function onUpload(event: FormEvent) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    uploadFile.mutate(file, {
      onSuccess: () => {
        if (fileInput.current) fileInput.current.value = "";
      },
    });
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Documents</h1>
          <p className="muted">
            Permitted documents researchers may search when a brief allows uploaded documents. Text-based PDF, .txt and
            .md only; scanned or encrypted PDFs are rejected.
          </p>
        </div>
      </div>

      {canUpload && (
        <Card title="Upload a document">
          <form className="row wrap" onSubmit={onUpload}>
            <input ref={fileInput} type="file" accept=".pdf,.txt,.md,application/pdf,text/plain" aria-label="Document file" />
            <button type="submit" className="btn btn-primary" disabled={uploadFile.isPending}>
              {uploadFile.isPending ? "Uploading…" : "Upload"}
            </button>
          </form>
          {uploadFile.isError && <ErrorBanner error={uploadFile.error} title="Upload rejected" />}
          {uploadFile.isSuccess && (
            <p className="small muted" role="status">
              Indexed {uploadFile.data.filename}: {uploadFile.data.chunks} searchable passage(s).
            </p>
          )}
        </Card>
      )}

      <Card title="Search documents">
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(query.trim());
          }}
        >
          <input aria-label="Search documents" value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="encryption key rotation" />
          <button type="submit" className="btn btn-secondary">Search</button>
        </form>
        {search.isFetching && <Spinner label="Searching…" />}
        {search.data && search.data.length === 0 && <p className="muted">No matching passages.</p>}
        {search.data && search.data.length > 0 && (
          <ul className="evidence-list">
            {search.data.map((hit) => (
              <li key={`${hit.upload_id}-${hit.locator}`}>
                <p className="small muted">{hit.filename} · {hit.locator}</p>
                <blockquote>{hit.text}</blockquote>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Workspace documents">
        {uploads.isPending && <Spinner />}
        {uploads.isError && <ErrorBanner error={uploads.error} title="Could not load documents" />}
        {uploads.data?.length === 0 && <EmptyState title="No documents yet" />}
        {uploads.data && uploads.data.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Document</th>
                <th scope="col">Size</th>
                <th scope="col">Passages</th>
                <th scope="col">Uploaded</th>
                <th scope="col"><span className="visually-hidden">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {uploads.data.map((u) => (
                <tr key={u.id}>
                  <td>
                    <strong>{u.title ?? u.filename}</strong>
                    <div className="small muted">{u.filename}{u.pages ? ` · ${u.pages} page(s)` : ""}</div>
                  </td>
                  <td className="nowrap">{formatSize(u.size_bytes)}</td>
                  <td>{u.chunks}</td>
                  <td className="nowrap">{u.uploaded_by} · {formatDateTime(u.created_at)}</td>
                  <td>
                    {(role === "admin" || u.uploaded_by_id === me.user_id) && (
                      <button type="button" className="btn btn-ghost" disabled={deleteUpload.isPending}
                              onClick={() => deleteUpload.mutate(u.id)} aria-label={`Delete ${u.filename}`}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
