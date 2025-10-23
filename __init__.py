bl_info = {
    "name": "CenLodify",
    "author": "Lrodas",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar (N) > CenLodify",
    "description": "Convert -Parts collections to -CenLods, or update existing -CenLods",
    "category": "Object",
}

import bpy
import os
from bpy.props import StringProperty, PointerProperty, BoolProperty
from bpy.types import PropertyGroup

# ---------- helpers ----------


def popup_error(msg):
    def draw(self, _):
        self.layout.label(text=msg)

    bpy.context.window_manager.popup_menu(draw, title="CenLodify Error!", icon="ERROR")


def findLayerCollection(layer, targetCollection):
    if layer.collection == targetCollection:
        return layer
    for child in layer.children:
        hit = findLayerCollection(child, targetCollection)
        if hit:
            return hit


def ApplyModsOnObject(obj):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.convert(target="MESH")
    obj.select_set(False)
    bpy.context.view_layer.objects.active = None


def JoinObjectsTogether(objects):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def SetOriginToWorldOrigin(targetObject):
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    cur = bpy.context.scene.cursor
    prev = cur.location.copy()
    cur.location = (0, 0, 0)
    bpy.context.view_layer.objects.active = targetObject
    targetObject.select_set(True)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    cur.location = prev
    targetObject.select_set(False)
    bpy.context.view_layer.objects.active = None


def ApplyScaleAndRotation(targetObject):
    bpy.context.view_layer.objects.active = targetObject
    targetObject.select_set(True)

    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    targetObject.select_set(False)
    bpy.context.view_layer.objects.active = None


def LinkIntoSameCollection(victim, invader):
    for col in victim.users_collection:
        col.objects.link(invader)


def CreateLod1Object(lod0Object):
    lod1 = lod0Object.copy()
    if lod0Object.data:
        lod1.data = lod0Object.data.copy()
    LinkIntoSameCollection(lod0Object, lod1)
    dec = lod1.modifiers.new(name="Lod1Decimate", type="DECIMATE")
    dec.decimate_type = "COLLAPSE"
    dec.ratio = 0.5
    lod1.name = lod0Object.name.removesuffix("_LOD0") + "_LOD1"
    return lod1


def _iter_objects_recursive(col, seen_ptrs):
    # Yield all unique objects in this collection and its children
    for obj in col.objects:
        pid = obj.as_pointer()
        if pid not in seen_ptrs:
            seen_ptrs.add(pid)
            yield obj
    for child in col.children:
        yield from _iter_objects_recursive(child, seen_ptrs)


def ConvertPartCollectionToLodCollection():
    partsCollection = bpy.context.view_layer.active_layer_collection.collection
    if not partsCollection.name.endswith("-Parts"):
        popup_error(
            f'The selected collection "{partsCollection.name}" does not end with "-Parts"'
        )
        return {"CANCELLED"}

    bpy.ops.object.select_all(action="DESELECT")

    # New collection name: "XXX-Parts" -> "XXX-V"
    lodCollectionName = partsCollection.name.removesuffix("-Parts") + "-CenLods"

    # if the lodcollection already existed, create a new collection instead, to prevent overwriting the old on accident
    existingLodCollection = bpy.data.collections.get(lodCollectionName)
    if existingLodCollection:
        lodCollectionName = (
            lodCollectionName.removesuffix("-CenLods") + "_NEW_FROM_PARTS-CenLods"
        )

    lodCollection = bpy.data.collections.new(lodCollectionName)
    bpy.context.scene.collection.children.link(lodCollection)

    duped = []
    seen_ptrs = set()
    partsCollectionObjects = list(_iter_objects_recursive(partsCollection, seen_ptrs))
    for obj in partsCollectionObjects:
        d = obj.copy()
        if obj.data:
            d.data = obj.data.copy()
        lodCollection.objects.link(d)
        ApplyModsOnObject(d)
        duped.append(d)

    if not duped:
        popup_error("No objects found to convert in the -Parts collection.")
        return {"CANCELLED"}

    joined = JoinObjectsTogether(duped)
    SetOriginToWorldOrigin(joined)
    ApplyScaleAndRotation(joined)

    joined.name = lodCollectionName.removesuffix("-CenLods") + "-V_LOD0"
    lod0 = joined
    lod1 = CreateLod1Object(lod0)

    # Hide the hi-poly (LOD0) by default
    lod0.hide_set(True)

    # Hide the original parts collection in the active view layer
    parts_layer = findLayerCollection(
        bpy.context.view_layer.layer_collection, partsCollection
    )
    if parts_layer:
        parts_layer.exclude = True

    return {"FINISHED"}


def UpdateLods():
    lodCollection = bpy.context.view_layer.active_layer_collection.collection
    if not lodCollection.name.endswith("-CenLods"):
        popup_error(
            f'The selected collection "{lodCollection.name}" does not end with "-CenLods"'
        )
        return {"CANCELLED"}

    lod1 = next((o for o in lodCollection.objects if o.name.endswith("_LOD1")), None)
    if lod1 is None:
        popup_error(
            f'Failed to find an object ending with "_LOD1" in "{lodCollection.name}"'
        )
        return {"CANCELLED"}

    oldDecimate = lod1.modifiers.get("Lod1Decimate")
    if not oldDecimate or oldDecimate.type != "DECIMATE":
        popup_error(f'Could not find "Lod1Decimate" (DECIMATE) on "{lod1.name}"')
        return {"CANCELLED"}

    old_ratio = oldDecimate.ratio

    # Remove old LOD1
    bpy.data.objects.remove(lod1, do_unlink=True)

    lod0 = next((o for o in lodCollection.objects if o.name.endswith("_LOD0")), None)
    if lod0 is None:
        popup_error(
            f'Failed to find an object ending with "_LOD0" in "{lodCollection.name}"'
        )
        return {"CANCELLED"}

    newLod1 = CreateLod1Object(lod0)
    newDec = newLod1.modifiers.get("Lod1Decimate")
    newDec.ratio = old_ratio

    lod0.hide_set(True)
    return {"FINISHED"}


def ExportCenLodCollection(pathString):
    targetCollection = bpy.context.view_layer.active_layer_collection.collection

    absolutePath = bpy.path.abspath(pathString) if pathString else ""
    if not absolutePath:
        popup_error("Forgot to set export directory.")
        return {"CANCELLED"}
    os.makedirs(absolutePath, exist_ok=True)

    seen = set()
    objs = [
        o for o in _iter_objects_recursive(targetCollection, seen) if o.type == "MESH"
    ]
    if not objs:
        popup_error(
            "Collection " + targetCollection.name + " did not have any mesh objects."
        )
        return {"CANCELLED"}



    layer = findLayerCollection(bpy.context.view_layer.layer_collection, targetCollection)
    prev_layer_exclude = layer.exclude if layer else None
    prev_layer_hide_vp = getattr(layer, "hide_viewport", None) if layer else None
    if layer:
        layer.exclude = False
        if prev_layer_hide_vp is not None:
            layer.hide_viewport = False

    prev_hidden = {o: o.hide_get() for o in objs}
    for o in objs:
        o.hide_set(False)



    previousActiveObject = bpy.context.view_layer.objects.active
    try:
        for obj in objs:
            bpy.ops.object.select_all(action="DESELECT")
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            filename = obj.name
            filepath = os.path.join(absolutePath, f"{filename}.fbx")

            bpy.ops.export_scene.fbx(
                filepath=filepath,
                use_selection=True,
                object_types={"MESH"},
                use_triangles=True,
                axis_forward="Y",
                axis_up="Z",
                apply_scale_options="FBX_SCALE_ALL",
                mesh_smooth_type="FACE",
                use_mesh_modifiers=True,
                add_leaf_bones=False,
                bake_anim=False,
                path_mode="AUTO",
            )
            
    finally: 
        for o, was_hidden in prev_hidden.items():
            o.hide_set(was_hidden)
        if layer:
            layer.exclude = prev_layer_exclude
            if prev_layer_hide_vp is not None:
                layer.hide_viewport = prev_layer_hide_vp

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = previousActiveObject
    # previousActiveObject.select_set(True)

    return {"FINISHED"}


# ---------- UI ----------
class CENLODIFY_OT_CenExport(bpy.types.Operator):
    bl_idname = "cenlodify.export"
    bl_label = "Export CenLods"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # targetCollection = context.view_layer.active_layer_collection.collection
        # if not targetCollection or not targetCollection.name.endswith("-CenLods"):
        #     popup_error(
        #         f'Active collection must end with "-CenLods" (got "{targetCollection.name if targetCollection else "<none>"}").'
        #     )
        #     return {"CANCELLED"}
        pathString = context.scene.cenlodify.export_path
        return ExportCenLodCollection(pathString)


class CENLODIFY_OT_process(bpy.types.Operator):
    bl_idname = "cenlodify.process"
    bl_label = "Convert / Update LODs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        col = context.view_layer.active_layer_collection.collection
        name = col.name if col else "<none>"
        if not col:
            popup_error("No active collection selected.")
            return {"CANCELLED"}

        if name.endswith("-Parts"):
            return ConvertPartCollectionToLodCollection()
        elif name.endswith("-CenLods"):
            return UpdateLods()
        else:
            popup_error('Active collection must end with "-Parts" or "-CenLods".')
            return {"CANCELLED"}


class CENLODIFY_PG_settings(PropertyGroup):
    export_path: StringProperty(
        name="Export Path",
        description="The export path",
        default="",
        subtype="DIR_PATH",
    )


class CENLODIFY_OT_ChooseExportPath(bpy.types.Operator):
    bl_idname = "cenlodify.pick_path"
    bl_label = "Choose export path"
    bl_options = {"REGISTER", "UNDO"}

    directorypath: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.cenlodify.export_path = self.directorypath
        return {"FINISHED"}


class CENLODIFY_PT_panel(bpy.types.Panel):
    bl_label = "CenLodify"
    bl_idname = "CENLODIFY_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CenLodify"

    def draw(self, context):
        layout = self.layout
        col = (
            context.view_layer.active_layer_collection.collection
            if context.view_layer.active_layer_collection
            else None
        )
        layout.label(text=f"Active: {col.name if col else '<none>'}")

        row = layout.row(align=True)
        row.prop(context.scene.cenlodify, "export_path", text="")
        # row.operator("cenlodify.pick_path", text="", icon="FILE_FOLDER")

        layout.operator("cenlodify.process", icon="MOD_DECIM")
        layout.operator("cenlodify.export", icon="EXPORT")


# ---------- register ----------

classes = (
    CENLODIFY_PG_settings,
    CENLODIFY_OT_process,
    CENLODIFY_OT_CenExport,
    CENLODIFY_OT_ChooseExportPath,
    CENLODIFY_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.cenlodify = PointerProperty(type=CENLODIFY_PG_settings)


def unregister():
    del bpy.types.Scene.cenlodify
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
