/**
 * Read-only data access. The Postgres pool sets
 * `default_transaction_read_only=on` for every checked-out connection; DuckDB
 * is opened with the read-only flag. Connections are NOT created during module
 * import — call `connect()` explicitly so unit tests can run without a live DB.
 */

import pg from "pg";

export interface DataAccess {
  pgPool: pg.Pool;
  /** Path of the DuckDB file we will open. Real handle is materialized lazily by tools. */
  duckdbPath: string;
  close(): Promise<void>;
}

export interface ConnectOptions {
  databaseUrl: string;
  duckdbPath: string;
}

export async function connect(opts: ConnectOptions): Promise<DataAccess> {
  const pool = new pg.Pool({
    connectionString: opts.databaseUrl,
    application_name: "penge-mcp",
  });

  pool.on("connect", (client) => {
    void client.query("SET default_transaction_read_only = on");
  });

  // Eagerly verify the URL is reachable so startup fails fast in dev.
  const probe = await pool.connect();
  try {
    await probe.query("SELECT 1");
  } finally {
    probe.release();
  }

  return {
    pgPool: pool,
    duckdbPath: opts.duckdbPath,
    async close() {
      await pool.end();
    },
  };
}
