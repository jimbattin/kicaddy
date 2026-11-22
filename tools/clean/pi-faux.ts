/**
 * Test-only pi extension for tools/clean: a scripted model (pi-ai's faux provider, no credentials) that builds the
 * NE555 example, tries to overwrite the schematic the session holds, queries nets, and renders. On session start it
 * prints the kicaddy tools and commands pi registered as a `KICADDY_SMOKE {...}` line on stderr.
 */
import { fauxAssistantMessage, fauxProvider, fauxText, fauxToolCall } from "@earendil-works/pi-ai";

export default function (pi: any): void {
	const script = process.env.KICADDY_SMOKE_SCRIPT!;
	const out = process.env.KICADDY_SMOKE_OUT!;
	const faux = fauxProvider();
	const call = (name: string, args: Record<string, unknown>) =>
		fauxAssistantMessage([fauxToolCall(name, args)], { stopReason: "toolUse" });
	faux.setResponses([
		call("kicaddy_build", { script, out }),
		call("write", { path: `${out}/ne555_blinker.kicad_sch`, content: "overwritten" }),
		call("kicaddy_query", { what: "nets" }),
		call("kicaddy_render", {}),
		fauxAssistantMessage([fauxText("smoke done")]),
	]);
	pi.registerProvider(faux.provider);
	pi.on("session_start", () => {
		const tools = pi.getAllTools().map((t: { name: string }) => t.name).filter((n: string) => n.startsWith("kicaddy_"));
		const commands = pi.getCommands().map((c: { name: string }) => c.name).filter((n: string) => n.includes("kicaddy"));
		console.error(`KICADDY_SMOKE ${JSON.stringify({ tools, commands })}`);
	});
}
