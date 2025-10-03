bl_info = {
    "name": "CenLodify",
    "author": "Lrodas",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar (N) > CenLodify",
    "description": "Convert -Parts collections to -V with LODs, or update existing -V",
    "category": "Object",
}

import bpy

# ---------- helpers ----------

def popup_error(msg):
    def draw(self, _):
        self.layout.label(text=msg)
    bpy.context.window_manager.popup_menu(draw, title="CenLodify Error!", icon='ERROR')

def findLayerCollection(layer, targetCollection):
    if layer.collection == targetCollection:
        return layer
    for child in layer.children:
        hit = findLayerCollection(child, targetCollection)
        if hit:
            return hit

def ApplyModsOnObject(obj):
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.convert(target='MESH')
    obj.select_set(False)
    bpy.context.view_layer.objects.active = None




def JoinObjectsTogether(objects):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active





def SetOriginToWorldOrigin(targetObject):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    cur = bpy.context.scene.cursor
    prev = cur.location.copy()
    cur.location = (0, 0, 0)
    bpy.context.view_layer.objects.active = targetObject
    targetObject.select_set(True)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
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
    dec = lod1.modifiers.new(name="Lod1Decimate", type='DECIMATE')
    dec.decimate_type = 'COLLAPSE'
    dec.ratio = 0.5
    lod1.name = lod0Object.name.removesuffix("_LOD0") + "_LOD1"
    return lod1





def ConvertPartCollectionToLodCollection():
    partsCollection = bpy.context.view_layer.active_layer_collection.collection
    if not partsCollection.name.endswith("-Parts"):
        popup_error(f'The selected collection "{partsCollection.name}" does not end with "-Parts"')
        return {'CANCELLED'}

    bpy.ops.object.select_all(action='DESELECT')

    # New collection name: "XXX-Parts" -> "XXX-V"
    lodCollectionName = partsCollection.name.removesuffix("-Parts") + "-V"

    # if the lodcollection already existed, create a new collection instead, to prevent overwriting the old on accident
    existingLodCollection = bpy.data.collections.get(lodCollectionName)
    if existingLodCollection:
        lodCollectionName = lodCollectionName.removesuffix("-V") + "_NEW_FROM_PARTS-V"

    lodCollection = bpy.data.collections.new(lodCollectionName)
    bpy.context.scene.collection.children.link(lodCollection)

    duped = []
    for obj in partsCollection.objects:
        d = obj.copy()
        if obj.data:
            d.data = obj.data.copy()
        lodCollection.objects.link(d)
        ApplyModsOnObject(d)
        duped.append(d)

    if not duped:
        popup_error("No objects found to convert in the -Parts collection.")
        return {'CANCELLED'}

    joined = JoinObjectsTogether(duped)
    SetOriginToWorldOrigin(joined)
    ApplyScaleAndRotation(joined)

    joined.name = lodCollectionName + "_LOD0"
    lod0 = joined
    lod1 = CreateLod1Object(lod0)

    # Hide the hi-poly (LOD0) by default
    lod0.hide_set(True)

    # Hide the original parts collection in the active view layer
    parts_layer = findLayerCollection(bpy.context.view_layer.layer_collection, partsCollection)
    if parts_layer:
        parts_layer.exclude = True

    return {'FINISHED'}




def UpdateLods():
    lodCollection = bpy.context.view_layer.active_layer_collection.collection
    if not lodCollection.name.endswith("-V"):
        popup_error(f'The selected collection "{lodCollection.name}" does not end with "-V"')
        return {'CANCELLED'}

    lod1 = next((o for o in lodCollection.objects if o.name.endswith("_LOD1")), None)
    if lod1 is None:
        popup_error(f'Failed to find an object ending with "_LOD1" in "{lodCollection.name}"')
        return {'CANCELLED'}

    oldDecimate = lod1.modifiers.get("Lod1Decimate")
    if not oldDecimate or oldDecimate.type != 'DECIMATE':
        popup_error(f'Could not find "Lod1Decimate" (DECIMATE) on "{lod1.name}"')
        return {'CANCELLED'}

    old_ratio = oldDecimate.ratio

    # Remove old LOD1
    bpy.data.objects.remove(lod1, do_unlink=True)

    lod0 = next((o for o in lodCollection.objects if o.name.endswith("_LOD0")), None)
    if lod0 is None:
        popup_error(f'Failed to find an object ending with "_LOD0" in "{lodCollection.name}"')
        return {'CANCELLED'}

    newLod1 = CreateLod1Object(lod0)
    newDec = newLod1.modifiers.get("Lod1Decimate")
    newDec.ratio = old_ratio

    lod0.hide_set(True)
    return {'FINISHED'}




# ---------- UI ----------

class CENLODIFY_OT_process(bpy.types.Operator):
    bl_idname = "cenlodify.process"
    bl_label = "Convert/Update LODs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        col = context.view_layer.active_layer_collection.collection
        name = col.name if col else "<none>"
        if not col:
            popup_error("No active collection selected.")
            return {'CANCELLED'}

        if name.endswith("-Parts"):
            return ConvertPartCollectionToLodCollection()
        elif name.endswith("-V"):
            return UpdateLods()
        else:
            popup_error('Active collection must end with "-Parts" or "-V".')
            return {'CANCELLED'}




class CENLODIFY_PT_panel(bpy.types.Panel):
    bl_label = "CenLodify"
    bl_idname = "CENLODIFY_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "CenLodify"

    def draw(self, context):
        layout = self.layout
        col = context.view_layer.active_layer_collection.collection if context.view_layer.active_layer_collection else None
        layout.label(text=f'Active: {col.name if col else "<none>"}')
        layout.operator("cenlodify.process", icon='MOD_DECIM')




# ---------- register ----------

classes = (CENLODIFY_OT_process, CENLODIFY_PT_panel)

def register():
    for c in classes:
        bpy.utils.register_class(c)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
