/** Error hierarchy for the WebUI, mirroring the repo-wide PengeError contract. */

export class PengeError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = new.target.name;
    this.code = code;
  }
}

/** Raised when the read API is unreachable, returns a non-2xx status, or
 * returns a payload that fails schema validation. */
export class PengeApiError extends PengeError {
  readonly status: number | null;

  constructor(code: string, message: string, status: number | null = null) {
    super(code, message);
    this.status = status;
  }
}
