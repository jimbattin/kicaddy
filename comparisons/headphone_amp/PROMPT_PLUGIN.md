# Goal
Produce a schematic for a basic headphone amplifier as a human-readable image.

# Common requirements
- Circuit: a basic headphone amplifier for typical 16-32 ohm headphones, driven from a line-level or phone source. You choose the topology, the supply (battery or single supply is fine) and whether it is mono or stereo. Component values must be electrically sound, with the key design equations and reasoning stated.
- Output: a schematic image (PNG) that a human can read: no overlapping parts, text or wires; junction dots at T connections; a short note on the drawing with key values or equations. Look at your own output image with the read tool and iterate until it is clean.
- Verify electrical correctness by whatever means your method allows.

# Isolation rules (strict)
- Work only inside your assigned output directory, plus any tool/library locations your task explicitly permits.
- Do NOT list, read or search other directories under /tmp. Do NOT read agent:// or history:// URIs. Do NOT message other agents.

# Final report
The output file paths; a circuit summary with values and reasoning; how you verified it; and the problems you hit along the way.

# Target
Your output directory is the current directory. Put your design script and every output here.

# Method (required)
Use the `kicaddy` plugin: read its skill (`skill://kicaddy`) and follow it. Do not read the plugin's source or any
directory outside the current one except the skill's own files.

# Acceptance
The common requirements. The build exits 0. The crop image is clean.
