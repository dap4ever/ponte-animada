"""Acessorios presos ao personagem (uma arma na mao, por exemplo).

Cada acessorio e um arquivo 3D + o osso que o carrega + a matriz dele no espaco local
desse osso. Esse espaco local e o mesmo no Blender e no visualizador (three.js/glTF):
origem na cabeca do osso, eixos do osso. Por isso a matriz que a interface manda e usada
aqui sem conversao de eixos (tests/check_props.mjs confere).
"""

from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Matrix

from . import scene

PREFIX = "PROP_"
# (x, y, z) do Blender -> (x, z, -y) do glTF.
BLENDER_TO_GLTF = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))


def attach_props(arm_obj, props: list[dict]) -> list[str]:
    """Importa e prende os acessorios. ``props``: [{id, file, bone, matrix}].

    ``matrix`` sao os 16 numeros da matriz local ao osso, por colunas (como o three.js guarda).
    Devolve avisos sobre o que nao pode ser preso.
    """
    notes = []
    arm = arm_obj.data
    for prop in props:
        bone = prop.get("bone")
        if not bone or not prop.get("matrix"):
            continue
        if bone not in arm.bones:
            notes.append(f"Acessório '{prop.get('name', prop['id'])}' não foi preso: o osso '{bone}' não existe.")
            continue
        new_objects = scene.import_into_scene(Path(prop["file"]))
        new_set = set(new_objects)
        holder = bpy.data.objects.new(PREFIX + prop["id"], None)
        bpy.context.scene.collection.objects.link(holder)
        bpy.context.view_layer.update()
        for obj in new_objects:
            if obj.parent not in new_set:
                world = obj.matrix_world.copy()
                obj.parent = holder
                obj.matrix_world = world

        m = prop["matrix"]
        # O visualizador posiciona o GLB do acessorio, cujo conteudo esta em Y-para-cima; aqui
        # o mesmo conteudo esta em Z-para-cima. Dai a troca de eixos antes da matriz.
        local = Matrix([[m[row + 4 * col] for col in range(4)] for row in range(4)]) @ BLENDER_TO_GLTF
        # A matriz e relativa ao osso em repouso; prende com a armature em repouso.
        previous = arm.pose_position
        arm.pose_position = "REST"
        bpy.context.view_layer.update()
        holder.parent = arm_obj
        holder.parent_type = "BONE"
        holder.parent_bone = bone
        holder.matrix_world = arm_obj.matrix_world @ arm.bones[bone].matrix_local @ local
        bpy.context.view_layer.update()
        arm.pose_position = previous
    bpy.context.view_layer.update()
    return notes
