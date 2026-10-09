export class PengeError extends Error {
  constructor(
    message: string,
    readonly code: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = new.target.name;
  }
}

export class ToolInputError extends PengeError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "tool/input_invalid", options);
  }
}

export class ToolUnknownError extends PengeError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "tool/unknown", options);
  }
}

export class ToolDataError extends PengeError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "tool/data_invalid", options);
  }
}

export class ToolNotFoundError extends PengeError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "tool/not_found", options);
  }
}

export class SourceCoverageError extends PengeError {
  constructor(message: string, options?: ErrorOptions) {
    super(message, "source/coverage_invalid", options);
  }
}
