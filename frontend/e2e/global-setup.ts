import { spawn, spawnSync, type ChildProcess } from "node:child_process";

import { BACKEND_DIR, BACKEND_ENV, E2E_DATABASE_URL, PYTHON } from "../playwright.config";

function python(args: string[], extraEnv: Record<string, string> = {}): void {
  const result = spawnSync(PYTHON, args, {
    cwd: BACKEND_DIR,
    env: { ...process.env, ...BACKEND_ENV, ...extraEnv },
    encoding: "utf-8",
  });
  if (result.status !== 0) {
    throw new Error(`python ${args.join(" ")} failed:\n${result.stdout}\n${result.stderr}`);
  }
}

/** Reset the dedicated E2E database, migrate, seed demo users, and start a worker. */
export default async function globalSetup(): Promise<() => Promise<void>> {
  if (!E2E_DATABASE_URL) {
    throw new Error("AOS_E2E_DATABASE_URL is not set (environment or backend/.env)");
  }
  python([
    "-c",
    "from sqlalchemy import text; from app.db.session import get_engine\n" +
      "with get_engine().begin() as c:\n" +
      "    c.execute(text('DROP SCHEMA IF EXISTS lg CASCADE'))\n" +
      "    c.execute(text('DROP SCHEMA IF EXISTS public CASCADE'))\n" +
      "    c.execute(text('CREATE SCHEMA public'))",
  ]);
  python(["-m", "alembic", "upgrade", "head"]);
  python(["-m", "app.cli", "seed-demo"]);

  const worker: ChildProcess = spawn(PYTHON, ["-m", "app.workers.runner"], {
    cwd: BACKEND_DIR,
    env: { ...process.env, ...BACKEND_ENV },
    stdio: "ignore",
  });
  return async () => {
    worker.kill();
  };
}
