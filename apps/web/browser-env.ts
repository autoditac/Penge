import { z } from "zod";

const port = z
  .string()
  .regex(/^[0-9]+$/)
  .transform(Number)
  .pipe(z.number().int().min(1).max(65535));
const ports = z
  .object({
    PENGE_E2E_API_PORT: port.default(8000),
    PENGE_E2E_WEB_PORT: port.default(5173),
  })
  .refine((value) => value.PENGE_E2E_API_PORT !== value.PENGE_E2E_WEB_PORT, {
    message: "Browser API and preview ports must be different",
  })
  .parse(process.env);

export const apiPort = ports.PENGE_E2E_API_PORT;
export const webPort = ports.PENGE_E2E_WEB_PORT;
export const apiUrl = `http://127.0.0.1:${apiPort}`;
export const webUrl = `http://127.0.0.1:${webPort}`;
