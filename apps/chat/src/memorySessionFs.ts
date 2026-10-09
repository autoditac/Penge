import { posix } from "node:path";

import type { SessionFsFileInfo, SessionFsProvider } from "@github/copilot-sdk";

const MAX_SESSION_FS_BYTES = 8 * 1024 * 1024;

interface MemoryFile {
  content: string;
  birthtime: string;
  mtime: string;
}

function fileSystemError(code: "ENOENT" | "ENOSPC", message: string): Error {
  return Object.assign(new Error(message), { code });
}

function normalizedPath(path: string): string {
  return posix.resolve("/", path);
}

export class BoundedMemorySessionFs implements SessionFsProvider {
  private readonly files = new Map<string, MemoryFile>();
  private readonly directories = new Set<string>(["/"]);
  private totalBytes = 0;

  async readFile(path: string): Promise<string> {
    const file = this.files.get(normalizedPath(path));
    if (file === undefined) {
      throw fileSystemError("ENOENT", "session file does not exist");
    }
    return file.content;
  }

  async writeFile(path: string, content: string): Promise<void> {
    const target = normalizedPath(path);
    this.ensureParents(target);
    const existing = this.files.get(target);
    const previousBytes = existing === undefined ? 0 : Buffer.byteLength(existing.content);
    const nextBytes = Buffer.byteLength(content);
    if (this.totalBytes - previousBytes + nextBytes > MAX_SESSION_FS_BYTES) {
      throw fileSystemError("ENOSPC", "bounded session memory is exhausted");
    }
    const now = new Date().toISOString();
    this.files.set(target, {
      content,
      birthtime: existing?.birthtime ?? now,
      mtime: now,
    });
    this.totalBytes = this.totalBytes - previousBytes + nextBytes;
  }

  async appendFile(path: string, content: string): Promise<void> {
    const target = normalizedPath(path);
    await this.writeFile(target, `${this.files.get(target)?.content ?? ""}${content}`);
  }

  async exists(path: string): Promise<boolean> {
    const target = normalizedPath(path);
    return this.files.has(target) || this.directories.has(target);
  }

  async stat(path: string): Promise<SessionFsFileInfo> {
    const target = normalizedPath(path);
    const file = this.files.get(target);
    if (file !== undefined) {
      return {
        isFile: true,
        isDirectory: false,
        size: Buffer.byteLength(file.content),
        mtime: file.mtime,
        birthtime: file.birthtime,
      };
    }
    if (this.directories.has(target)) {
      const timestamp = new Date(0).toISOString();
      return {
        isFile: false,
        isDirectory: true,
        size: 0,
        mtime: timestamp,
        birthtime: timestamp,
      };
    }
    throw fileSystemError("ENOENT", "session path does not exist");
  }

  async mkdir(path: string, recursive: boolean): Promise<void> {
    const target = normalizedPath(path);
    if (!recursive && !this.directories.has(posix.dirname(target))) {
      throw fileSystemError("ENOENT", "session parent directory does not exist");
    }
    this.ensureParents(posix.join(target, "placeholder"));
    this.directories.add(target);
  }

  async readdir(path: string): Promise<string[]> {
    return (await this.readdirWithTypes(path)).map((entry) => entry.name);
  }

  async readdirWithTypes(
    path: string,
  ): Promise<Array<{ name: string; type: "file" | "directory" }>> {
    const target = normalizedPath(path);
    if (!this.directories.has(target)) {
      throw fileSystemError("ENOENT", "session directory does not exist");
    }
    const entries = new Map<string, "file" | "directory">();
    for (const file of this.files.keys()) {
      if (posix.dirname(file) === target) {
        entries.set(posix.basename(file), "file");
      }
    }
    for (const directory of this.directories) {
      if (directory !== target && posix.dirname(directory) === target) {
        entries.set(posix.basename(directory), "directory");
      }
    }
    return [...entries]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, type]) => ({
        name,
        type,
      }));
  }

  async rm(path: string, recursive: boolean, force: boolean): Promise<void> {
    const target = normalizedPath(path);
    const file = this.files.get(target);
    if (file !== undefined) {
      this.files.delete(target);
      this.totalBytes -= Buffer.byteLength(file.content);
      return;
    }
    if (!this.directories.has(target)) {
      if (force) return;
      throw fileSystemError("ENOENT", "session path does not exist");
    }
    const prefix = target === "/" ? "/" : `${target}/`;
    const hasChildren = [...this.files.keys(), ...this.directories].some(
      (entry) => entry !== target && entry.startsWith(prefix),
    );
    if (hasChildren && !recursive) {
      throw new Error("session directory is not empty");
    }
    for (const [filePath, stored] of this.files) {
      if (filePath.startsWith(prefix)) {
        this.files.delete(filePath);
        this.totalBytes -= Buffer.byteLength(stored.content);
      }
    }
    for (const directory of [...this.directories]) {
      if (directory === target || directory.startsWith(prefix)) {
        this.directories.delete(directory);
      }
    }
    this.directories.add("/");
  }

  async rename(source: string, destination: string): Promise<void> {
    const from = normalizedPath(source);
    const to = normalizedPath(destination);
    if (from === to) {
      if (!(await this.exists(from))) {
        throw fileSystemError("ENOENT", "session path does not exist");
      }
      return;
    }
    const file = this.files.get(from);
    if (file !== undefined) {
      this.ensureParents(to);
      const replaced = this.files.get(to);
      if (replaced !== undefined) {
        this.totalBytes -= Buffer.byteLength(replaced.content);
      }
      this.files.delete(from);
      this.files.set(to, file);
      return;
    }
    if (!this.directories.has(from)) {
      throw fileSystemError("ENOENT", "session path does not exist");
    }
    this.ensureParents(posix.join(to, "placeholder"));
    const directoryMoves = [...this.directories]
      .filter((entry) => entry === from || entry.startsWith(`${from}/`))
      .map((entry) => [entry, `${to}${entry.slice(from.length)}`] as const);
    const fileMoves = [...this.files]
      .filter(([entry]) => entry.startsWith(`${from}/`))
      .map(([entry, stored]) => [entry, `${to}${entry.slice(from.length)}`, stored] as const);
    for (const [entry] of directoryMoves) this.directories.delete(entry);
    for (const [, target] of directoryMoves) this.directories.add(target);
    for (const [entry] of fileMoves) this.files.delete(entry);
    for (const [, target, stored] of fileMoves) this.files.set(target, stored);
  }

  private ensureParents(path: string): void {
    let directory = posix.dirname(path);
    const parents: string[] = [];
    while (!this.directories.has(directory)) {
      parents.push(directory);
      const parent = posix.dirname(directory);
      if (parent === directory) break;
      directory = parent;
    }
    for (const parent of parents.reverse()) this.directories.add(parent);
  }
}
