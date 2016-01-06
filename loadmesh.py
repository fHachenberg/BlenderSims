import PySims.skn_bmf
import PySims.cmx_bcf
import PySims.cfp

from PySims.far import FarFile

import bpy
import bmesh
import mathutils

from functools import cmp_to_key

def create_armature(skel_stream, objname=None):
    '''
    @param skel_stream DataStream containing exactly one skeleton, which is imported as an armature
    @param objname Name for scene object pointing to armature to be created. Default is game's internal name for skeleton
    @return scene object linked to armature
    '''
    scene = bpy.context.scene

    #load skeleton data
    sceleton_obj = PySims.cmx_bcf.read_characterdata_from_stream(skel_stream)
    assert len(sceleton_obj.sceletons) == 1 #sanity check
    sceleton = sceleton_obj.sceletons[0]

    if objname == None:
        objname = sceleton.name
    armature = bpy.data.armatures.new(objname)

    armobj = bpy.data.objects.new(objname, armature)
    scene.objects.link(armobj)
    #bpy.ops.object.mode_set(mode='OBJECT')
    #bpy.ops.object.select_all(action='DESELECT')
    bpy.context.scene.objects.active = armobj
    armobj.select = True
    bpy.ops.object.mode_set(mode='EDIT')

    editbones = {} #here we collect the already-created editbones for parent references
    for bone in sceleton.bones:
        editbone = armature.edit_bones.new(bone.name)
        editbone.name = bone.name
        #editbone.use_connect = True
        #editbone.use_local_location = True

        if bone.parent_name != "NULL":
            editbone.parent = editbones[bone.parent_name]
            parent_mat = editbone.parent.matrix
        else:
            parent_mat = mathutils.Matrix.Identity(4)
        editbones[bone.name] = editbone

        #currently applying the animation only leads to a correct result
        #if we initialize the bone orientations here using identity quaternions!
        #Our current theory to explain this fact is, that the sims animations do not contain
        #relative rotations (relative to the rest pose) but absolute rotations. And since
        #blender uses RELATIVE rotations for animation, the correct result is achieved if
        #the relative rotation of the bones is indistinguishable from an absolute rotation
        #which is the case if the rest pose is the identity!
        #This should - for consistency - also apply to the positions of bones. But it's a
        #different issue there: using the rest pose, we create a correct mesh in blender
        #(and we have to because vertex positions are given relative to their bound bone in
        #skn files)
        a,b,c,d = [1.0, 0., 0., 0.]#bone.quat
        quaternion = mathutils.Quaternion([-a,b,c,d])
        #print(bone.name, bone.quat)
        quatmat = quaternion.to_matrix().to_4x4()
        offset = mathutils.Vector(bone.pos)

        #editbone.head = [a+b for (a,b) in zip(bone.pos, parent_head)]
        #print(bone.name, editbone.matrix)

        editbone.matrix = parent_mat * quatmat * mathutils.Matrix.Translation(offset)
        editbone.tail = editbone.head + quatmat*mathutils.Vector([0.,0.,1.0])
        #editbone.length = 1.0
        #print(bone.name, quatmat * mathutils.Matrix.Translation(offset) )

    bpy.ops.object.mode_set(mode='OBJECT')

    return armobj

def add_mesh_to_armature(armobj, mesh_stream, texfilenames, custom_texname = None, objname = None):
    '''
    @param armobj scene object for armature
    @param mesh_stream skn/bmf DataStream
    @param texfilenames object allowing to retrieve filename of texture via texfilenames[texture_basename]
    @param custom_texname Texture to apply to mesh (overwriting default texture eventually)
    @param objname Name for scene object pointing to mesh to be created. Default is game's internal name for mesh
    @return scene mesh object
    '''
    scene = bpy.context.scene
    stream = mesh_stream

    #load armature data from armature object
    armature = armobj.data

    #load mesh data
    mesh = PySims.skn_bmf.read_deformablemesh_from_stream(stream)

    #if no objname was given, the game's name for it is used
    if objname == None:
        objname = mesh.name
    blmesh = bpy.data.meshes.new(objname)

    #vertices are specified relative to their bone. So now we
    #have to go through all bones and transform the vertices according
    #to the bone's coordinate system
    locs  = [mathutils.Vector(p[0:3]) for p in mesh.vertices[0:len(mesh.uvcoords)]]
    #norms = [mathutils.Vector(p[3:6]) for p in mesh.vertices]
    for boneidx, bonename in enumerate(mesh.bones):
        armbone = armature.bones[armature.bones.find(bonename)]
        binding = mesh.bonebindings[boneidx]
        _, frst_wghtone, num_wghtone, frst_wghtotr, num_wghtotr = binding
        for i in range(frst_wghtone, frst_wghtone+num_wghtone):
            locs[i] = armbone.matrix_local * locs[i].to_4d()

    blmesh.from_pydata([a[:3] for a in locs], [], mesh.faces)
    blmesh.update()

    blobj = bpy.data.objects.new(objname, blmesh)
    armmod = blobj.modifiers.new("arm", 'ARMATURE')
    armmod.object = armobj

    #create vertex groups
    for boneidx, bonename in enumerate(mesh.bones):

        vgroup = blobj.vertex_groups.new(bonename)
        binding = mesh.bonebindings[boneidx]
        _, frst_wghtone, num_wghtone, frst_wghtotr, num_wghtotr = binding
        vgroup.add(range(frst_wghtone, frst_wghtone+num_wghtone), 1.0, 'ADD')
        for i in range(frst_wghtotr, frst_wghtotr+num_wghtotr):
            vertidx, weight = mesh.blenddata[i]
            vgroup.add([vertidx], float(weight)/65568.0, 'ADD')

    scene.objects.link(blobj)

    #load uv coordinates onto mesh

    #initialize uv coordinates of vertices
    bm = bmesh.new()
    bm.from_mesh(blmesh)

    bm.faces.layers.tex.verify()
    uv_layer = bm.loops.layers.uv.verify()

    for face in bm.faces:
        for i, loop in enumerate(face.loops):
            uv = loop[uv_layer].uv
            #v dimension has to be mirrored to achieve correct orientation of vertices on texture
            uv[:] = (mesh.uvcoords[loop.vert.index][0], 1.0-mesh.uvcoords[loop.vert.index][1])

    bm.to_mesh(blmesh)
    bm.free() #todo(optimization) Can we reuse the bm object for multiple objects?

    #There are 2 options to load a tex here:
    # - default texture is available and user has not demanded a custom one
    # - user has demanded a custom texture
    default_tex_basename = mesh.texfilename
    tex_filename = None
    if custom_texname != None: #no default tex available
        tex_filename = texfilenames[custom_texname]
    elif default_tex_basename != "x": #x indicates that no default texture was specified in the skn file
        tex_filename = texfilenames[default_tex_basename]

    if tex_filename != None:
        set_mesh_uvtexture(blobj, tex_filename)

    return blobj

def set_mesh_uvtexture(meshobj, tex_filename):
    '''
    Loads texture file as image and installs it as the
    used uv mapped image for blmesh
    @param meshobj scene mesh object
    '''
    #access data block
    blmesh = meshobj.data

    #load texture
    tex_image = bpy.data.images.load(tex_filename)

    #set texture as active image for all polys in mesh
    for uv_face in blmesh.uv_textures.active.data:
        print(tex_image)
        uv_face.image = tex_image

def add_action_from_skill(armobj, anim_stream, skill_choice, anim_dta_streams):
    '''
    loads animation data from cmx/bcf skill description into new action

    @param armobj scene object linked to armature data
    @param anim_stream cmx/bcf DataStream containing the motion to load onto the armature
    @param skill_choice name or index of the skill to load
    @param anim_dta_streams dict (basename animation file as used in cmx/bcp file, stream to actual animation file)
    '''

    scene = bpy.context.scene

    framelength = 1.0
    animdta = armobj.animation_data_create()

    #load animation data
    stream = anim_stream
    objdta = PySims.cmx_bcf.read_characterdata_from_stream(stream)
    assert len(objdta.skills) != 0
    skill = None
    #print("Available skills: %s" % [s.name for s in objdta.skills])
    if type(skill_choice) == int:
        skill = objdta.skills[skill_choice]
    else:
        try:
            skill = next(s for s in objdta.skills if s.name == skill_name)
        except StopIteration:
            raise Exception("No skill of name '%s' found in cmx data" % skill_name)
    action = bpy.data.actions.new(skill.name)
    animdta.action = action

    #load raw keyframe data for skill

    raw_frames = PySims.cfp.read_animdta_from_cfp_stream(anim_dta_streams[skill.ani_name], skill.num_pos, skill.num_pos, skill.num_pos, skill.num_rot, skill.num_rot, skill.num_rot, skill.num_rot)
    for motion in skill.motions:
        if motion.pos_used:
            #bone locations
            data_path = 'pose.bones["%s"].location' % motion.bone_name
            for axis_i in range(3):
                curve = action.fcurves.new(data_path=data_path, index=axis_i)
                keyframe_points = curve.keyframe_points
                keyframe_points.add(motion.num_frames)
                for frame_i in range(motion.num_frames):
                    keyframe_points[frame_i].co = (framelength*frame_i, raw_frames[axis_i][motion.pos_off+frame_i])

        if motion.rot_used:
            #bone rotations
            data_path = 'pose.bones["%s"].rotation_quaternion' % motion.bone_name
            #print(motion.bone_name)
            #for i in range(motion.num_frames):
                #print(raw_frames[3][motion.rot_off+i], raw_frames[4][motion.rot_off+i], raw_frames[5][motion.rot_off+i], raw_frames[6][motion.rot_off+i])
            for axis_i in range(4):
                curve = action.fcurves.new(data_path=data_path, index=axis_i)
                keyframe_points = curve.keyframe_points
                keyframe_points.add(motion.num_frames)
                for frame_i in range(motion.num_frames):
                    if axis_i == 0:
                        keyframe_points[frame_i].co = (framelength*frame_i, -raw_frames[axis_i+3][motion.rot_off+frame_i])
                    else:
                        keyframe_points[frame_i].co = (framelength*frame_i, raw_frames[axis_i+3][motion.rot_off+frame_i])

    return action
