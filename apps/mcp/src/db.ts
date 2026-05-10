/**
 * Read-only data access. Every connection checked out from the pool runs
 * `SET default_transaction_read_only = on` before it is returned to the
 * caller, so a forgotten or buggy tool cannot mutate the operational
 * database. DuckDB is opened read-only by tool authors via `duckdbPath`.
 *
 * Connections are NOT created during module import — call `connect()`
 * explicitly so unit tests can run without a live DB.
 */

import pg from "pg";

export interface DataAccess {
  pgPool: pg.Pool;
  /** Check out a connection that has already been forced read-only. Always release in a finally block. */
  acquire(): Promise<pg.PoolClient>;
  /** Path of the DuckDB file we will open. Real handle is materialized lazily by tools. */
  duckdbPath: string;
  close(): Promise<void>;
}

export interface ConnectOptions {
  databaseUrl: string;
  duckdbPath: string;
}

async function enforceReadOnly(client: pg.PoolClient): Promise<void> {
  await client.query("SET default_transaction_read_only = on");
}

export async function connect(opts: ConnectOptions): Promise<DataAccess> {
  const pool = new pg.Pool({
    connectionString: opts.databaseUrl,
    application_name: "penge-mcp",
  });

  const acquire = async (): Promise<pg.PoolClient> => {
    const client = await pool.connect();
    try {
      await enforceReadOnly(client);
    } catch (err) {
      client.release();
      throw err;
    }
    return client;
  };

  // Fail fast in dev if the URL is unreachable or the role cannot SET.
  const probe = await acquire();
  try {
    await probe.query("SELECT 1");
  } finally {
    probe.release();
  }

  return {
    pgPool: pool,
    acquire,
    duckdbPath: opts.duckdbPath,
    async close() {
      await pool.end();
    },
  };
}
