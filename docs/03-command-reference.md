# Command reference

All 134 commands with a handler in build `10.99.0-6860-gbdd2930d2b`, from two sources that agree exactly: the
`registerHandler<Request, Response>` calls in the source at commit `bdd2930d2b`, and a probe of the running headless
server with every message type in the protos.

## Reading the tables

| Column | Meaning |
|---|---|
| Request | Message to pack into `ApiRequest.message`. Full name is the section's package plus this name. |
| Response | Message type in `ApiResponse.message`. `Empty` is `google.protobuf.Empty`. |
| Needs | Open document that makes the handler exist: `sch` schematic, `pcb` board, `sym` symbol in the library editor, `fp` footprint in the library editor, `—` none. Several entries: routed by `DocumentSpecifier` type. |
| Headless | Whether `kicad-cli api-server` serves it, per the source's `checkForHeadless` and `IsGUI` guards. `no` means `AS_UNIMPLEMENTED`. |
| Live | `✔` succeeded against the headless server. `✘` observed returning `AS_UNIMPLEMENTED` there. Blank: registered, not exercised. |

Field-level detail: the `.proto` file named under each heading.

### Base

Package `kiapi.common.commands` · `api/proto/common/commands/base_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `GetVersion` | `GetVersionResponse` | — | yes | ✔ | `major`/`minor`/`full_version`. |
| `GetKiCadBinaryPath` | `PathResponse` | — | yes | ✔ | Absolute path of a bundled binary, e.g. `kicad-cli`. |
| `GetPaths` | `GetPathsResponse` | — | yes | ✔ | User plugin/template/settings dirs and stock library dirs. |
| `Ping` | `Empty` | — | yes | ✔ | Liveness check. |
| `GetTextExtents` | `Box2` | — | yes | ✔ | Bounding box of a text item without placing it. One round trip (about 10 ms) per text: 254 texts on `pic_programmer` took 2.5 s per lint. The box moves with `position` and nothing else (882 fields, labels, and notes of the design corpus and `pic_programmer`, in every rotation and alignment they use: 0 differences), so the lint asks once per distinct text and attribute set, at the origin, and keeps the answer for the server's life. |
| `GetTextAsShapes` | `GetTextAsShapesResponse` | — | yes |  | Text rendered to polygons/segments. |
| `GetPluginSettingsPath` | `StringResponse` | — | yes |  | Writable per-plugin data dir (not created). |

### Project and documents

Package `kiapi.common.commands` · `api/proto/common/commands/project_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `GetNetClasses` | `NetClassesResponse` | — | yes | ✔ | Project netclasses; `project` optional. |
| `SetNetClasses` | `Empty` | — | yes | ✔ | `merge_mode` MMM_MERGE or MMM_REPLACE; `Default` is never erased. Saved to `.kicad_pro` `net_settings.classes`; unset `board` fields are omitted (inherit from `Default`). `NetClass` is in `common.types.project_settings`. |
| `GetNetClassAssignments` | `NetClassAssignmentsResponse` | — | yes |  | Net → netclass and pattern assignments. |
| `SetNetClassAssignments` | `Empty` | — | yes | ✔ | `pattern_assignments` (`NetClassPatternAssignment`) saved to `.kicad_pro` `net_settings.netclass_patterns`. |
| `ExpandTextVariables` | `ExpandTextVariablesResponse` | — / sch, pcb, fp | yes |  | `${VAR}` expansion; handled per document type (project, board, schematic). |
| `GetTextVariables` | `TextVariables` | — | yes | ✔ | Needs `type=DOCTYPE_PROJECT` and a full `project` (name and path). |
| `SetTextVariables` | `Empty` | — | yes |  | Same specifier rules as `GetTextVariables`. |
| `OpenDocument` | `OpenDocumentResponse` | — | yes | ✔ | Headless only. `path` is a file path (project/schematic/board) or `Lib:Item` (symbol/footprint). One project at a time. |
| `CloseDocument` | `Empty` | — | yes | ✔ | Headless only. Discards unsaved changes without error. Closing the project closes everything. |
| `CloseAllDocuments` | `Empty` | — | yes | ✔ | Headless only. |
| `CreateDocument` | `OpenDocumentResponse` | — | yes | ✔ | Headless only. Schematic or board only; in memory until saved; creates the project if absent. |
| `SaveDocument` | `Empty` | sch, pcb, sym, fp | yes | ✔ | Writes the document and project files. |

### Editor: documents, items, commits

Package `kiapi.common.commands` · `api/proto/common/commands/editor_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `BeginCommit` | `BeginCommitResponse` | sch, pcb, sym, fp | yes | ✔ | Returns a commit id; later edits are staged until `EndCommit`. One commit opened with the root sheet's header covers calls on child sheets. Items placed or created inside it do not exist until it ends ([02](02-ipc-protocol.md#commits)). |
| `EndCommit` | `EndCommitResponse` | sch, pcb, sym, fp | yes | ✔ | `CMA_COMMIT` or `CMA_DROP`. |
| `CreateItems` | `CreateItemsResponse` | sch, pcb, sym, fp | yes | ✔ | Items are `Any`; optional `container` = existing symbol/footprint id. |
| `UpdateItems` | `UpdateItemsResponse` | sch, pcb, sym, fp | yes | ✔ | Whole-item replace; `field_mask` is ignored. |
| `DeleteItems` | `DeleteItemsResponse` | sch, pcb, sym, fp | yes | ✔ | By KIID; one `deleted_items` status per id. A schematic symbol, power symbol, wire, and local label in one commit: all `IDS_OK` (M7). |
| `HitTest` | `HitTestResponse` | sch, pcb, sym, fp | yes |  |  |
| `GetDocumentModifiedState` | `GetDocumentModifiedStateResponse` | sch, pcb, sym, fp | yes | ✔ |  |
| `GetTitleBlockInfo` | `TitleBlockInfo` | sch, pcb, sym, fp | yes | ✔ |  |
| `SetTitleBlockInfo` | `Empty` | sch, pcb, sym, fp | yes | ✔ |  |
| `GetOpenDocuments` | `GetOpenDocumentsResponse` | sch, pcb, sym, fp | yes | ✔ | `AS_UNHANDLED` when no document of that type is open, and always for `DOCTYPE_PROJECT`. |
| `SaveCopyOfDocument` | `Empty` | sch, pcb, sym, fp | yes |  | Parent directory must already exist. |
| `RevertDocument` | `Empty` | sch, pcb, sym, fp | yes; **no** for fp | ✔ | Reload from disk. The reloaded schematic items are not byte-identical to the API-built ones ([02](02-ipc-protocol.md#commits)). |
| `SaveDocumentAs` | `Empty` | sch, pcb | yes |  | Headless only. Save and switch to the new path/project. |
| `SaveDocumentToString` | `SavedDocumentResponse` | sch, pcb, fp | yes | ✔ | Full s-expression text of the document. |
| `SaveSelectionToString` | `SavedSelectionResponse` | sch, pcb, fp | **no** |  |  |
| `GetItems` | `GetItemsResponse` | sch, pcb, sym, fp | yes | ✔ | Optional `types` filter. Schematic: one sheet via `sheet_path`, otherwise all sheets. |
| `GetItemsById` | `GetItemsResponse` | sch, pcb, sym, fp | yes | ✔ |  |
| `GetSelection` | `SelectionResponse` | sch, pcb, fp | **no** | ✘ |  |
| `ClearSelection` | `Empty` | sch, pcb, fp | **no** |  |  |
| `AddToSelection` | `SelectionResponse` | sch, pcb, fp | **no** |  |  |
| `RemoveFromSelection` | `SelectionResponse` | sch, pcb, fp | **no** |  |  |
| `FocusOnItems` | `Empty` | sch, pcb, fp | **no** |  |  |
| `GetPageSettings` | `PageSettings` | sch, pcb | yes | ✔ |  |
| `SetPageSettings` | `PageSettings` | sch, pcb | yes | ✔ | Page size and orientation, e.g. `PS_A5` + `PO_LANDSCAPE`. |
| `OpenLibraryItem` | `Empty` | sym, fp | sym only |  | Switch the open library editor to another item. |
| `RunAction` | `RunActionResponse` | pcb, fp | **no** | ✘ | Raw TOOL_ACTION by name; explicitly not a stable API. Board/footprint editors only. |
| `GetBoundingBox` | `GetBoundingBoxResponse` | pcb, fp | yes |  |  |
| `ParseAndCreateItemsFromString` | `CreateItemsResponse` | pcb, fp | yes |  | Paste-style s-expression import. No schematic handler. |

### Libraries

Package `kiapi.common.commands` · `api/proto/common/commands/library_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `GetLibraryItems` | `LibraryItemsResponse` | — | yes | ✔ | LIB_IDs in the named libraries. Answered `AS_UNHANDLED` until a document was open. |
| `GetLibraryStatuses` | `LibraryStatusResponse` | — | yes | ✔ | Per-library load state and table row. `scope` is required. |
| `ReloadLibrary` | `LibraryCommandStatus` | — | yes | ✔ | Asynchronous. Reloads existing rows only: a project row added after the document opened returns `LCS_NOT_FOUND`. Rewritten files of loaded rows are picked up without it. |
| `GetItemsFromLibrary` | `GetItemsResponse` | — | yes | ✔ | Full `SchematicSymbol`/`Footprint` definitions by LIB_ID, not in request order. Answered `AS_UNHANDLED` until a document was open. |
| `LoadAllLibraries` | `LibraryCommandStatus` | — | yes | ✔ | Headless only. Asynchronous preload; poll `GetLibraryStatuses`. |

### Variants

Package `kiapi.common.commands` · `api/proto/common/commands/variant_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `GetVariants` | `VariantsResponse` | sch, pcb | yes | ✔ |  |
| `AddVariant` | `Empty` | sch, pcb | yes |  |  |
| `DeleteVariant` | `Empty` | sch, pcb | yes |  |  |
| `RenameVariant` | `Empty` | sch, pcb | yes |  |  |
| `CopyVariant` | `Empty` | sch, pcb | yes |  |  |
| `SetVariantDescription` | `Empty` | sch, pcb | yes |  |  |
| `SetCurrentVariant` | `Empty` | sch, pcb | yes |  |  |
| `GetCurrentVariant` | `CurrentVariantResponse` | sch, pcb | yes |  |  |

### Tasks (common)

Package `kiapi.common.tasks` · `api/proto/common/tasks.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `GetTaskStatus` | `TaskStatusResponse` | — | yes | ✔ | The only request (besides task-result fetches) served while a task runs. |

### Schematic

Package `kiapi.schematic.commands` · `api/proto/schematic/schematic_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `GetSchematicHierarchy` | `SchematicHierarchyResponse` | sch | yes | ✔ | Sheet tree with `SheetPath`s; needs `project` in the specifier. |
| `GetSchematicNetlist` | `SchematicNetlistResponse` | sch | yes | ✔ | Net name → item KIIDs per sheet; `types=[KOT_SCH_PIN]` gives pins only, adding `KOT_SCH_LABEL`/`KOT_SCH_GLOBAL_LABEL` lists each net's label KIIDs (M7). Covers the whole hierarchy whatever the `sheet_path`. |
| `PlaceSymbolFromLibrary` | `PlaceFromLibraryResponse` | sch | yes | ✔ | Optional orientation, unit, reference; no mirror (set `transform.mirror_x`/`mirror_y` on an `UpdateItems`). Fails `symbol … not found` while libraries are still loading. Junctions that need the placed symbol's pins are deleted by the commit cleanup until the symbol has been through `UpdateItems` ([04](04-workflows.md#behaviors-to-know)). |

### Schematic tasks

Package `kiapi.schematic.tasks` · `api/proto/schematic/schematic_tasks.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `StartErcTask` | `StartTaskResponse` | sch | yes | ✔ | Returns a task token. |
| `GetErcTaskResult` | `ErcTaskResult` | sch | yes | ✔ | `ErcMarker` list with positions, items, severity; every sheet, with `sheet_specific_path` per marker. |

### Schematic export jobs

Package `kiapi.schematic.jobs` · `api/proto/schematic/schematic_jobs.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `RunSchematicJobExportSvg` | `RunJobResponse` | sch | yes | ✔ |  |
| `RunSchematicJobExportDxf` | `RunJobResponse` | sch | yes |  |  |
| `RunSchematicJobExportPdf` | `RunJobResponse` | sch | yes | ✔ | `SJSM_ALL_SHEETS` from the root with a file `output_path`: one multi-page PDF. |
| `RunSchematicJobExportPs` | `RunJobResponse` | sch | yes |  |  |
| `RunSchematicJobExportPng` | `RunJobResponse` | sch | yes | ✔ | `dpi`, `plot_background_color`; `plot_drawing_sheet=false` plots the drawing alone. The PNG has no dpi metadata. |
| `RunSchematicJobExportNetlist` | `RunJobResponse` | sch | yes | ✔ |  |
| `RunSchematicJobExportBOM` | `RunJobResponse` | sch | yes |  | Requires a field list or a preset name. |

### Board

Package `kiapi.board.commands` · `api/proto/board/board_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `GetBoardStackup` | `BoardStackupResponse` | pcb, fp | yes | ✔ | Read-only; no stackup write command is implemented. |
| `GetBoardEnabledLayers` | `BoardEnabledLayersResponse` | pcb, fp | yes | ✔ |  |
| `GetGraphicsDefaults` | `GraphicsDefaultsResponse` | pcb, fp | yes |  |  |
| `GetBoardBoundingBox` | `BoardBoundingBoxResponse` | pcb, fp | yes | ✔ | All items, physical layers, or Edge.Cuts only. |
| `GetPadShapeAsPolygon` | `PadShapeAsPolygonResponse` | pcb, fp | yes |  |  |
| `CheckPadstackPresenceOnLayers` | `PadstackPresenceResponse` | pcb, fp | yes |  |  |
| `InteractiveMoveItems` | `Empty` | pcb, fp | **no** |  | Starts the GUI move tool. |
| `FlipItems` | `FlipItemsResponse` | pcb, fp | yes |  | Flip to the other board side; KiCad updates children. |
| `GetVisibleLayers` | `BoardLayers` | pcb, fp | **no** | ✘ |  |
| `SetVisibleLayers` | `Empty` | pcb, fp | **no** |  |  |
| `GetActiveLayer` | `BoardLayerResponse` | pcb, fp | **no** |  |  |
| `SetActiveLayer` | `Empty` | pcb, fp | **no** |  |  |
| `SetBoardEnabledLayers` | `BoardEnabledLayersResponse` | pcb | yes |  | Destructive: content on removed layers is deleted. |
| `GetBoardDesignRules` | `BoardDesignRulesResponse` | pcb | yes | ✔ | Constraints, predefined sizes, severities, exclusions. |
| `SetBoardDesignRules` | `BoardDesignRulesResponse` | pcb | yes |  |  |
| `GetCustomDesignRules` | `CustomRulesResponse` | pcb | yes | ✔ | `.kicad_dru` rules, structured. |
| `SetCustomDesignRules` | `CustomRulesResponse` | pcb | yes |  |  |
| `GetEmbeddedFiles` | `EmbeddedFiles` | pcb | yes |  |  |
| `AddEmbeddedFiles` | `Empty` | pcb | yes |  |  |
| `SetEmbeddedFiles` | `Empty` | pcb | yes |  |  |
| `GetBoardOrigin` | `Vector2` | pcb | yes |  | Grid or drill origin. |
| `SetBoardOrigin` | `Empty` | pcb | yes |  |  |
| `GetBoardLayerName` | `BoardLayerNameResponse` | pcb | yes |  |  |
| `GetBoardLayerByName` | `BoardLayerResponse` | pcb | yes |  |  |
| `GetNets` | `NetsResponse` | pcb | yes | ✔ | Optional netclass filter. |
| `GetConnectedItems` | `GetItemsResponse` | pcb | yes |  | Copper connectivity from seed items. |
| `GetItemsByNet` | `GetItemsResponse` | pcb | yes |  |  |
| `GetItemsByNetClass` | `GetItemsResponse` | pcb | yes |  |  |
| `GetNetClassForNets` | `NetClassForNetsResponse` | pcb | yes |  | Effective (merged) netclass per net. |
| `RefillZones` | `Empty` | pcb | yes | ✔ | Synchronous in headless mode. |
| `ImportNetlist` | `ImportNetlistResponse` | pcb | yes | ✔ | "Update PCB from schematic" from a netlist file; `dry_run` reports only. |
| `ImportSpecctraSession` | `ImportSpecctraSessionResponse` | pcb | yes |  | Apply an external autorouter `.ses` result. |
| `GetBoardEditorAppearanceSettings` | `BoardEditorAppearanceSettings` | pcb | **no** |  |  |
| `SetBoardEditorAppearanceSettings` | `Empty` | pcb | **no** |  |  |
| `GetBoardPlotSettings` | `BoardPlotSettingsResponse` | pcb | yes | ✔ |  |
| `SetBoardPlotSettings` | `Empty` | pcb | yes |  |  |
| `InjectDrcError` | `InjectDrcErrorResponse` | pcb | yes |  | Adds a custom DRC marker. |
| `PlaceFootprintFromLibrary` | `PlaceFromLibraryResponse` | pcb | yes |  | Places a library footprint; optional orientation and layer. |

### Board tasks

Package `kiapi.board.tasks` · `api/proto/board/board_tasks.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `StartRefillZonesTask` | `StartTaskResponse` | pcb | yes |  |  |
| `StartDrcTask` | `StartTaskResponse` | pcb | yes | ✔ | Options: all track errors, schematic parity, require zones filled. |
| `GetDrcTaskResult` | `DrcTaskResult` | pcb | yes | ✔ | `DrcMarker` list with positions, items, rule, severity. |

### Board export jobs

Package `kiapi.board.jobs` · `api/proto/board/board_jobs.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `RunBoardJobExport3D` | `RunJobResponse` | pcb | yes | ✔ |  |
| `RunBoardJobExportRender` | `RunJobResponse` | pcb | yes | ✔ | Raytraced PNG/JPEG. Only format, size, side set: unlit black silhouette. Also high quality, stackup colours, and the four `light_*_intensity` fields set: lit. Which option matters was not isolated. |
| `RunBoardJobExportSvg` | `RunJobResponse` | pcb | yes | ✔ |  |
| `RunBoardJobExportDxf` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportPdf` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportPs` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportPng` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportGerbers` | `RunJobResponse` | pcb | yes | ✔ |  |
| `RunBoardJobExportDrill` | `RunJobResponse` | pcb | yes | ✔ |  |
| `RunBoardJobExportPosition` | `RunJobResponse` | pcb | yes | ✔ |  |
| `RunBoardJobExportSpecctraDsn` | `RunJobResponse` | pcb | yes |  | Input for an external autorouter. |
| `RunBoardJobExportGencad` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportIpc2581` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportIpcD356` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportODB` | `RunJobResponse` | pcb | yes |  |  |
| `RunBoardJobExportStats` | `RunJobResponse` | pcb | yes | ✔ |  |
| `RunBoardJobExportIdf` | `RunJobResponse` | pcb | yes |  |  |

### Cross-probe

Package `kiapi.common.commands` · `api/proto/common/commands/cross_probe_commands.proto`

| Request | Response | Needs | Headless | Live | Notes |
|---|---|---|---|---|---|
| `CrossProbeAnnounce` | `CrossProbeAnnounceResponse` | sch, pcb | yes |  | Internal (standalone-editor cross-probing). |
| `SyncSelection` | `SyncSelectionResponse` | sch, pcb | **no** |  | Cross-probe. |
| `HighlightNets` | `HighlightNetsResponse` | sch, pcb | **no** |  | Cross-probe. |

## Declared in the protos, no handler

These messages exist in `api/proto/` but returned `AS_UNHANDLED` with schematic, board, symbol, and footprint all
open, and have no `registerHandler` call in the source.

| Message | Package | Consequence |
|---|---|---|
| `UpdateBoardStackup` | `kiapi.board.commands` | Stackup is read-only. `SetBoardEnabledLayers` can change the copper layer count and enabled layers. |
| `GetLibraryTable` | `kiapi.common.commands` | Library tables cannot be listed as tables. `GetLibraryStatuses` returns each row. |
| `AddLibraryTableEntry` | `kiapi.common.commands` | Libraries cannot be registered through the API. |
| `UpdateLibraryTableEntry` | `kiapi.common.commands` | |
| `DeleteLibraryTableEntry` | `kiapi.common.commands` | |
| `SearchLibraries` | `kiapi.common.commands` | No server-side search. `GetLibraryItems` lists names per library for client-side matching. |
| `RefreshEditor` | `kiapi.common.commands` | |
| `FocusOnItem` | `kiapi.common.commands` | `FocusOnItems` exists, GUI only. |

## Item types accepted by `CreateItems` and `UpdateItems`

From the type allow-lists in the source **[src]**. Entries marked ✔ were created or updated through the headless
server.

### Schematic sheet (`kiapi.schematic.types`)

| Message | Notes |
|---|---|
| `SchematicLine` ✔ | `type`: `SLT_WIRE`, `SLT_BUS`, `SLT_GRAPHIC` |
| `Junction` ✔ | |
| `NoConnectMarker` ✔ | |
| `BusEntry` | Wire-to-bus and bus-to-bus |
| `LocalLabel` ✔, `GlobalLabel` ✔, `HierarchicalLabel` ✔, `DirectiveLabel` ✔ | |
| `SchematicText` ✔, `SchematicTextBox`, `SchematicTable` | Multi-line `SchematicText` is centred vertically on its position by default |
| `SchematicGraphicShape`, `SchematicImage` | |
| `SchematicRuleArea`, `Group` | |
| `SchematicSymbolInstance` ✔ (update) | Placement from a library is `PlaceSymbolFromLibrary` ✔ |
| `SheetSymbol` ✔ | Creates a hierarchical sheet; the child file is written on save |

`SchematicPin` and `SheetPin` are children of a symbol or sheet. `SheetPin` through `container` = a sheet symbol
fails with `ISC_INVALID_TYPE`; put sheet pins in `SheetSymbol.pins` on `CreateItems` or `UpdateItems`.

### Symbol in the library editor

`SchematicField`, `SchematicPin`, `SchematicGraphicShape`, `SchematicImage`, `SchematicText`, `SchematicTextBox`,
`SchematicTable`. Creating/updating the whole `SchematicSymbol` is rejected with
`whole-symbol create/update is not supported; edit the symbol's child items instead`. Reading a symbol worked:
`GetItems` on `Device:LED` returned 1 `SchematicSymbol`, 5 shapes, 6 fields, 2 pins.

### Board (`kiapi.board.types`)

| Message | Notes |
|---|---|
| `Track` ✔, `Arc`, `Via` ✔ | |
| `Zone` ✔ | Copper, graphical, rule area, teardrop |
| `BoardGraphicShape` ✔ | Segment, rectangle, arc, circle, polygon, bezier, ellipse |
| `BoardText`, `BoardTextBox`, `Table`, `Barcode`, `Dimension`, `ReferenceImage`, `ReferencePoint` | |
| `FootprintInstance` ✔ (update) | Placement from a library is `PlaceFootprintFromLibrary`; from a netlist, `ImportNetlist` ✔ |
| `Pad`, `Field`, 3D body | Footprint children |
| `Group`, `GridItem`, `Constraint` | |
| `TuningPattern`, `ViaStitchArea` | Generators |
| `DrillChart`, `DrillMap`, `StackupTable` | Fabrication drawing objects |

Inside a footprint (`container` set, or a footprint open in the library editor): `Field`, `Barcode`, `BoardText`,
`BoardTextBox`, `BoardGraphicShape`, `ReferenceImage`, `Table`, `Pad`, `Zone`, `Group`, `Constraint`,
`ReferencePoint`, `Dimension`, 3D body. Reading a footprint worked: `GetItems` on `LED_SMD:LED_0603_1608Metric`
returned 2 pads, 9 shapes, 5 fields, 1 text.

### `GetItems` type filters

`KiCadObjectType` (`common/types/enums.proto`) has 55 values: `KOT_PCB_*` for board items, `KOT_SCH_*` for schematic
items, `KOT_LIB_SYMBOL`, and `KOT_WSG_*` for drawing-sheet items. `KOT_SCH_PIN` was rejected as a filter on a
schematic document; pins arrive inside their symbol's `definition.items`.
