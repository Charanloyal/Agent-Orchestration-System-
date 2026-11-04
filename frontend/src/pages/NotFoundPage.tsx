import { Link } from "react-router";
import { useDocumentTitle } from "../api/hooks";

export function NotFoundPage() {
  useDocumentTitle("Page not found");
  return (
    <div className="empty">
      <h1>Page not found</h1>
      <p className="muted">The page does not exist, or you do not have access to it.</p>
      <Link className="btn btn-secondary" to="/">Go to your runs</Link>
    </div>
  );
}
