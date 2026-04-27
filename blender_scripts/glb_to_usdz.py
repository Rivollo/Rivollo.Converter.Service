"""
Blender headless script: GLB → USDZ conversion.

Confirmed working on Blender 5.0.1 (snap) on Ubuntu.
Blender 5.0 supports native .usdz export — no manual zip workaround needed.

Called via:
  blender --background --python glb_to_usdz.py \
          -- --input /path/to/model.glb --output /path/to/model.usdz
"""

import os
import sys
import bpy


def parse_args():
    """Parse args after '--' separator (Blender's custom arg convention)."""
    argv = sys.argv
    if "--" not in argv:
        raise ValueError(
            "Usage: blender --background --python glb_to_usdz.py "
            "-- --input <glb_path> --output <usdz_path>"
        )
    args = argv[argv.index("--") + 1:]
    input_path, output_path = None, None
    for i, arg in enumerate(args):
        if arg == "--input" and i + 1 < len(args):
            input_path = args[i + 1]
        elif arg == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
    if not input_path or not output_path:
        raise ValueError("Both --input and --output are required.")
    return input_path, output_path


def main():
    input_path, output_path = parse_args()

    # ── Step 1: Clear default scene ───────────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # ── Step 2: Enable GLB import addon (required in headless Blender) ─
    import addon_utils
    addon_utils.enable("io_scene_gltf2", default_set=False)

    # ── Step 3: Import GLB ────────────────────────────────────────────
    print(f"[Blender] Importing GLB: {input_path}")
    import_result = bpy.ops.import_scene.gltf(filepath=input_path)
    if import_result != {"FINISHED"}:
        raise RuntimeError(f"GLB import failed — operator returned: {import_result}")

    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError(
            "GLB import produced no mesh objects — file may be empty "
            "or contain only cameras/lights."
        )
    print(f"[Blender] Imported {len(mesh_objects)} mesh object(s)")

    # ── Step 4: Prepare meshes ────────────────────────────────────────
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")

    # make_single_user prevents transform_apply crash on instanced meshes
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.make_single_user(object=True, obdata=True)
    bpy.ops.object.select_all(action="DESELECT")

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Bake transforms into vertex positions for correct USD placement
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # iPhone Quick Look requires triangle-only meshes
        tri_mod = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
        tri_mod.quad_method = "BEAUTY"
        tri_mod.ngon_method = "BEAUTY"
        bpy.ops.object.modifier_apply(modifier=tri_mod.name)

        obj.select_set(False)

    bpy.ops.object.select_all(action="DESELECT")

    # ── Step 5: Export directly to .usdz (native in Blender 5.0) ─────
    # generate_preview_surface converts materials to UsdPreviewSurface —
    # the only shader iOS Quick Look understands.
    print(f"[Blender] Exporting USDZ: {output_path}")
    export_result = bpy.ops.wm.usd_export(
        filepath=output_path,
        export_materials=True,
        generate_preview_surface=True,
        export_textures_mode="NEW",
        root_prim_path="/Root",
    )
    print(f"[Blender] Export result: {export_result}")

    if export_result != {"FINISHED"}:
        raise RuntimeError(f"USD export failed — operator returned: {export_result}")

    if not os.path.exists(output_path):
        raise RuntimeError(f"Export reported FINISHED but file not found: {output_path}")

    print(f"[Blender] Done → {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
