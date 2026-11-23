/**
 * kicaddy extension for omp / pi: tools over a session daemon (`kicaddy daemon`) that keeps one KiCad
 * api-server warm per session, a guard against editing the schematic files it holds open, and /kicaddy.
 * Structural host types only, so it needs no host package at compile time and loads on upstream pi too.
 */
import { type ChildProcess, execFile, spawn } from "node:child_process";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { Type } from "@sinclair/typebox";

// ---- minimal host surface (pi and omp both satisfy this) ----
interface HostCtx {
	cwd: string;
	agent?: { kind?: "main" | "sub" };
	ui: { notify: (msg: string, level?: "info" | "warning" | "error") => void };
}
type Content = { type: "text"; text: string } | { type: "image"; mimeType: string; data: string };
interface ToolDef<P> {
	name: string;
	label: string;
	description: string;
	parameters: unknown;
	approval?: "read" | "write" | "exec"; // omp approval tier (default exec); pi ignores it
	execute: (id: string, params: P, signal: AbortSignal | undefined, onUpdate: unknown, ctx: HostCtx) => Promise<{
		content: Content[];
		details?: unknown;
	}>;
}
interface ToolCallEvent {
	toolName?: string;
	input?: Record<string, unknown>;
}
interface HostAPI {
	on: (event: string, handler: (event: ToolCallEvent, ctx: HostCtx) => unknown) => void;
	registerTool: <P>(tool: ToolDef<P>) => void;
	registerCommand: (name: string, def: { description: string; handler: (args: string, ctx: HostCtx) => Promise<void> | void }) => void;
}

interface State {
	pid: number;
	server_pid: number | null;
	project_dir: string | null;
	root: string | null;
	files: string[];
	built: boolean;
	batches: number;
	kicad: string;
}
interface Response {
	id: number;
	ok: boolean;
	output: string;
	images: string[];
	state: State;
	fingerprint?: string | null;
}

const BIN = fileURLToPath(new URL("../bin/kicaddy", import.meta.url));
const STDERR_LINES = 40;
const ABORT_GRACE_MS = 5_000;

// Files held open by every daemon in this process (main session and subagents), for the edit/write guard.
const HELD = new Map<object, State>();

function runBin(args: string[], timeoutMs = 900_000): Promise<{ code: number; text: string }> {
	const { promise, resolve: done } = Promise.withResolvers<{ code: number; text: string }>();
	execFile("python3", [BIN, ...args], { maxBuffer: 16 * 1024 * 1024, timeout: timeoutMs }, (error, stdout, stderr) => {
		const code = error ? (typeof error.code === "number" ? error.code : 1) : 0;
		const text = `${stdout ?? ""}${stderr ?? ""}`.trim() || (error ? error.message : "");
		done({ code, text });
	});
	return promise;
}

class Daemon {
	private child: ChildProcess;
	private pending = new Map<number, { resolve: (r: Response) => void; reject: (e: Error) => void }>();
	private chain: Promise<unknown> = Promise.resolve();
	private nextId = 1;
	private stderrTail: string[] = [];
	private exitText = "";
	private aborted = false; // stopped by request(): an aborted call was still running
	exited = false;

	constructor(cwd: string, private onState: (state: State | undefined) => void) {
		this.child = spawn("python3", [BIN, "daemon"], { cwd, stdio: ["pipe", "pipe", "pipe"] });
		this.child.stdin!.on("error", () => {}); // a dead daemon is reported by "exit"
		createInterface({ input: this.child.stdout! }).on("line", (line) => {
			let response: Response;
			try {
				response = JSON.parse(line);
			} catch {
				return this.tail(line);
			}
			this.onState(response.state);
			const waiter = this.pending.get(response.id);
			this.pending.delete(response.id);
			waiter?.resolve(response);
		});
		createInterface({ input: this.child.stderr! }).on("line", (line) => this.tail(line));
		this.child.on("error", (e) => this.finish(`kicaddy daemon failed to start: ${e.message}`));
		this.child.on("exit", (code, signal) => this.finish(`kicaddy daemon exited (${signal ?? `code ${code}`})`));
	}

	private tail(line: string): void {
		this.stderrTail.push(line);
		if (this.stderrTail.length > STDERR_LINES) this.stderrTail.shift();
	}

	private finish(what: string): void {
		if (this.exited) return;
		this.exited = true;
		const lines = this.aborted
			? ["kicaddy daemon stopped: an aborted call was still running; build or open the project again"]
			: [what, ...this.stderrTail, "If it names a doctor command, run it (or /kicaddy doctor), then retry."];
		this.exitText = lines.join("\n");
		this.onState(undefined);
		for (const waiter of this.pending.values()) waiter.reject(new Error(this.exitText));
		this.pending.clear();
	}

	/** One request in flight. A build or batch runs design code, so one the host aborted that is still running
	 * ABORT_GRACE_MS later takes the daemon down with it; the next call starts a new one. */
	request(op: string, params: Record<string, unknown> = {}, signal?: AbortSignal): Promise<Response> {
		const send = () => {
			const { promise, resolve: done, reject } = Promise.withResolvers<Response>();
			if (this.exited || signal?.aborted) {
				reject(new Error(this.exited ? this.exitText : "aborted"));
				return promise;
			}
			const id = this.nextId++;
			this.pending.set(id, { resolve: done, reject });
			this.child.stdin!.write(`${JSON.stringify({ id, op, ...params })}\n`);
			const onAbort = () => {
				const timer = setTimeout(() => {
					this.aborted = true;
					this.child.kill("SIGTERM");
				}, ABORT_GRACE_MS);
				promise.finally(() => clearTimeout(timer)).catch(() => {});
			};
			signal?.addEventListener("abort", onAbort, { once: true });
			promise.finally(() => signal?.removeEventListener("abort", onAbort)).catch(() => {});
			return promise;
		};
		const result = this.chain.then(send, send);
		this.chain = result.catch(() => {});
		return result;
	}

	stop(): void {
		if (this.exited) return;
		this.child.stdin!.write(`${JSON.stringify({ id: 0, op: "shutdown" })}\n`);
		this.child.stdin!.end();
	}
}

function normalize(cwd: string, path: string): string {
	const full = resolve(cwd, path);
	try {
		return existsSync(full) ? realpathSync(full) : full;
	} catch {
		return full;
	}
}

/** Paths an edit/write call touches: `path` (write, pi's edit) and file headers in an omp edit payload. */
function targets(input: Record<string, unknown> | undefined): string[] {
	const out: string[] = [];
	if (typeof input?.path === "string") out.push(input.path);
	const payload = input?.input;
	if (typeof payload === "string") {
		const patterns = [
			/^\[(.+?)#[0-9A-Za-z]{4}\]\s*$/gm, // hashline
			/^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$/gm, // apply_patch
			/^# (.+?)\s*$/gm, // section mode
		];
		for (const pattern of patterns) for (const m of payload.matchAll(pattern)) out.push(m[1]);
	}
	return out;
}

export default function kicaddy(pi: HostAPI): void {
	const key = {};
	let daemon: Daemon | undefined;
	let state: State | undefined;
	let sweepPromise: Promise<unknown> | undefined;
	let swept = false;

	const setState = (next: State | undefined) => {
		state = next;
		if (next?.files.length) HELD.set(key, next);
		else HELD.delete(key);
	};

	async function ensureDaemon(ctx: HostCtx): Promise<Daemon> {
		if (!swept) {
			await (sweepPromise ?? runBin(["sweep"]));
			swept = true;
		}
		if (!daemon || daemon.exited) daemon = new Daemon(ctx.cwd, setState);
		return daemon;
	}

	function stopDaemon(): void {
		daemon?.stop();
		daemon = undefined;
		setState(undefined);
	}

	async function call(ctx: HostCtx, signal: AbortSignal | undefined, op: string, params: Record<string, unknown>) {
		const d = await ensureDaemon(ctx);
		const response = await d.request(op, params, signal);
		if (!response.ok) throw new Error(response.output);
		const content: Content[] = [{ type: "text", text: response.output }];
		for (const path of response.images ?? []) {
			content.push({ type: "image", mimeType: "image/png", data: readFileSync(path).toString("base64") });
		}
		return { content };
	}

	pi.on("session_start", (_event, ctx) => {
		if (ctx.agent?.kind !== "sub") sweepPromise = runBin(["sweep"]);
	});
	pi.on("session_shutdown", () => stopDaemon());

	pi.on("tool_call", (event, ctx) => {
		if (event?.toolName !== "edit" && event?.toolName !== "write") return;
		if (!HELD.size) return;
		for (const path of targets(event.input)) {
			const full = normalize(ctx.cwd, path);
			for (const held of HELD.values()) {
				if (held.files.includes(full)) {
					return {
						block: true,
						reason: `kicaddy holds ${full} open (project ${held.project_dir}). Use kicaddy_edit (for a project from kicaddy_build, or change build.py and rebuild); a direct edit would be overwritten by the next save.`,
					};
				}
			}
		}
	});

	// The first line of a description is the whole catalog entry where the host lists tools by name (omp).
	pi.registerTool<{ script: string; out?: string }>({
		name: "kicaddy_build",
		label: "kicaddy build",
		description:
			"Run a design build.py on this session's warm KiCad server (same output and files as `kicaddy run`) and keep the project open for kicaddy_query, kicaddy_render, kicaddy_edit.\nDiscards earlier kicaddy_edit batches.",
		parameters: Type.Object({
			script: Type.String({ description: "path to the design's build.py" }),
			out: Type.Optional(Type.String({ description: "output directory; default the script's directory" })),
		}),
		execute: (_id, params, signal, _onUpdate, ctx) =>
			call(ctx, signal, "build", {
				script: resolve(ctx.cwd, params.script),
				cwd: ctx.cwd,
				...(params.out ? { out: resolve(ctx.cwd, params.out) } : {}),
			}),
	});

	pi.registerTool<{ path: string; upgrade?: boolean }>({
		name: "kicaddy_open",
		label: "kicaddy open",
		description:
			"Open an existing KiCad project (directory, .kicad_pro, or root .kicad_sch) for kicaddy_query, kicaddy_render, and kicaddy_edit.\nA project saved by another KiCad release opens for query and render only, because a save rewrites it in this KiCad's file format; `upgrade: true` allows kicaddy_edit.",
		parameters: Type.Object({
			path: Type.String({ description: "project directory, .kicad_pro, or root .kicad_sch" }),
			upgrade: Type.Optional(
				Type.Boolean({
					description:
						"allow kicaddy_edit on a project saved by another KiCad release: the first committed batch rewrites every sheet in the running KiCad's file format, which that release cannot open. Only when the user has agreed",
				}),
			),
		}),
		approval: "read",
		execute: (_id, params, signal, _onUpdate, ctx) =>
			call(ctx, signal, "open", {
				path: resolve(ctx.cwd, params.path),
				...(params.upgrade === true ? { upgrade: true } : {}),
			}),
	});

	pi.registerTool<{ what: string; lib_ids?: string[]; refs?: string[]; dir?: string; sheet?: string; net?: string }>({
		name: "kicaddy_query",
		label: "kicaddy query",
		description:
			"Query the open project (placed symbols; with `refs` their pin points, body box and fields with anchor and box; nets as REF.PIN sets; ERC; LINT; `items`: the power symbols, wires, junctions, labels, notes, text boxes, frames and tables of a sheet, or of one net on it) or library pin offsets, body boxes and field positions in grid units (`lib_ids`, like `kicaddy pins`; no open project needed: the session directory's sym-lib-table is used, or `dir`'s).",
		parameters: Type.Object({
			what: Type.Union([
				Type.Literal("symbols"),
				Type.Literal("nets"),
				Type.Literal("erc"),
				Type.Literal("lint"),
				Type.Literal("items"),
				Type.Literal("pins"),
			]),
			lib_ids: Type.Optional(Type.Array(Type.String(), { description: "Library:Symbol ids, for what=pins" })),
			refs: Type.Optional(
				Type.Array(Type.String(), {
					description: "for what=symbols: only these references, each with its pin points, body box and fields",
				}),
			),
			dir: Type.Optional(
				Type.String({
					description:
						"for what=pins: project directory whose sym-lib-table to use, as `kicaddy pins --dir`; default the open project, else the session directory",
				}),
			),
			sheet: Type.Optional(
				Type.String({
					description:
						"sheet file stem: only that sheet's symbols, nets, ERC or LINT lines; for what=items the sheet to list (default the root sheet)",
				}),
			),
			net: Type.Optional(
				Type.String({
					description: "for what=items: only this net's items on the sheet; the full net name as what=nets prints it",
				}),
			),
		}),
		approval: "read",
		execute: (_id, params, signal, _onUpdate, ctx) =>
			call(ctx, signal, "query", {
				what: params.what,
				lib_ids: params.lib_ids ?? [],
				refs: params.refs ?? [],
				cwd: ctx.cwd,
				...(params.dir ? { dir: resolve(ctx.cwd, params.dir) } : {}),
				...(params.sheet ? { sheet: params.sheet } : {}),
				...(params.net ? { net: params.net } : {}),
			}),
	});

	pi.registerTool<{ sheet?: string; around?: string[]; box?: number[] }>({
		name: "kicaddy_render",
		label: "kicaddy render",
		description:
			"Plot cropped PNGs of every sheet of the open project (or the sheet with this file stem) and return them as images; with `around` or `box`, one image of that region.",
		parameters: Type.Object({
			sheet: Type.Optional(Type.String({ description: "sheet file stem; default every sheet" })),
			around: Type.Optional(
				Type.Array(Type.String(), {
					description:
						"references on one sheet: one image of the region around them (12 grid units of margin, grown to keep whole the parts, labels, notes, text boxes, tables and sheet boxes at its edge) instead of the sheet crops",
				}),
			),
			box: Type.Optional(
				Type.Array(Type.Number(), {
					minItems: 4,
					maxItems: 4,
					description: "[x0, y0, x1, y1] in grid units on `sheet` (default the root sheet): one image of that region",
				}),
			),
		}),
		approval: "write",
		execute: (_id, params, signal, _onUpdate, ctx) =>
			call(ctx, signal, "render", {
				...(params.sheet ? { sheet: params.sheet } : {}),
				...(params.around?.length ? { around: params.around } : {}),
				...(params.box !== undefined ? { box: params.box } : {}),
			}),
	});

	const pins = (description: string) => Type.Record(Type.String(), Type.String(), { description });
	const refs = (description: string) => Type.Array(Type.String(), { description });
	pi.registerTool<{ code: string; sheet?: string; expect?: Record<string, unknown>; strict?: boolean }>({
		name: "kicaddy_edit",
		label: "kicaddy edit",
		description:
			"Run Python builder calls as one batch on the open project; the netlist change is checked against `expect`, and a failed batch leaves the document unchanged.\nThe project comes from kicaddy_build or kicaddy_open. In `code`, `s` is the sheet, `sheets` maps file stems to sheets, and `project` is the project. Besides the build.py methods, items already in the document can be moved, removed, and changed (s.move, s.remove, s.remove_wire, s.remove_label, s.remove_no_connect, s.field(..., text=), s.flags, project.rename_net, s.note_text, s.remove_note): the kicaddy skill lists them. `expect` is required for a project from kicaddy_open ({} for no netlist change). Reports the netlist change and the ERC and LINT issues the batch added; a committed batch is saved.",
		parameters: Type.Object({
			code: Type.String({ description: "Python, e.g. s.symbol(\"R5\", \"Device:R\", (60, 30), value=\"1k\")" }),
			sheet: Type.Optional(Type.String({ description: "sheet file stem; default the root sheet" })),
			expect: Type.Optional(
				Type.Object(
					{
						add: Type.Optional(pins("new components: {ref: value}")),
						remove: Type.Optional(refs("removed components: their pins leave every net")),
						values: Type.Optional(pins("changed values: {ref: new value}")),
						connect: Type.Optional(
							pins("{\"REF.PIN\": target}: the pin joins target, a \"REF.PIN\", an existing net name, or a new net name"),
						),
						disconnect: Type.Optional(refs("\"REF.PIN\" pins that leave their net")),
						rename: Type.Optional(pins("{old full net name: new full net name}, as kicaddy_query nets prints them")),
					},
					{ additionalProperties: false, description: "the netlist change the batch makes; {} for none" },
				),
			),
			strict: Type.Optional(
				Type.Boolean({
					description: "drop the batch when it adds an ERC violation or a LINT line; they are reported as for an expect mismatch",
				}),
			),
		}),
		execute: (_id, params, signal, _onUpdate, ctx) =>
			call(ctx, signal, "edit", {
				code: params.code,
				...(params.sheet ? { sheet: params.sheet } : {}),
				...(params.expect !== undefined ? { expect: params.expect } : {}),
				...(params.strict === true ? { strict: true } : {}),
			}),
	});

	pi.registerCommand("kicaddy", {
		description: "kicaddy: config [CHOICE] | doctor | status | view [FILE]",
		handler: async (args, ctx) => {
			const text = args.trim();
			const command = text.split(/\s+/)[0] ?? "";
			const rest = text.slice(command.length).trim();
			const report = (r: { code: number; text: string }) => ctx.ui.notify(r.text, r.code === 0 ? "info" : "error");
			if (command === "config" && !rest) return report(await runBin(["config", "kicad"]));
			if (command === "config") {
				stopDaemon();
				const set = await runBin(["config", "kicad", rest]);
				report(set);
				if (set.code === 0) report(await runBin(["doctor"]));
				return;
			}
			if (command === "doctor") {
				ctx.ui.notify("running kicaddy doctor…", "info");
				stopDaemon();
				return report(await runBin(["doctor"]));
			}
			if (command === "status") {
				if (!daemon || daemon.exited) return ctx.ui.notify("kicaddy daemon not running", "info");
				try {
					return ctx.ui.notify((await daemon.request("status")).output, "info");
				} catch (e) {
					return ctx.ui.notify(String((e as Error).message), "error");
				}
			}
			if (command === "view") {
				const file = rest ? resolve(ctx.cwd, rest) : state?.root;
				if (!file) return ctx.ui.notify("nothing open; pass a file", "error");
				return report(await runBin(["view", file]));
			}
			ctx.ui.notify("usage: /kicaddy config [CHOICE] | doctor | status | view [FILE]", "warning");
		},
	});
}
