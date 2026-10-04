export interface ClosableResource {
  close(): Promise<void>;
}

export async function closeServiceResources(
  server: ClosableResource,
  store: ClosableResource,
): Promise<void> {
  const failures: unknown[] = [];
  try {
    await server.close();
  } catch (error) {
    failures.push(error);
  } finally {
    try {
      await store.close();
    } catch (error) {
      failures.push(error);
    }
  }
  if (failures.length > 0) {
    throw new AggregateError(failures, "chat service shutdown failed");
  }
}
