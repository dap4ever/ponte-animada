"""Animacao pronta num FBX (as do Mixamo) como fonte do retarget.

O retarget foi feito para o BVH do Kimodo: recebe, de cada junta, a rotacao global como
delta do descanso e a posicao, com os nomes do SOMA 77. Aqui a armature animada de um FBX e
lida quadro a quadro e entregue nesse mesmo formato, com cada osso chamado pela junta do
SOMA que faz o mesmo papel. Assim a animacao passa pelo mesmo retarget (correcao da pose de
descanso, escala da passada, medidas), seja qual for o esqueleto do personagem que a recebe.
"""

from __future__ import annotations

from pathlib import Path

import bpy
import numpy as np

from . import rigmap, scene
from .bvh import BvhMotion
from .retarget import SRC_TO_WORLD

# Tudo no projeto roda a 30 quadros por segundo (e o do Kimodo); o FBX e amostrado nesse ritmo.
FPS = 30


def load_fbx_motion(path: Path) -> BvhMotion:
    """Le a animacao de ``path`` na cena atual e tira de la o que entrou. Devolve o movimento."""
    sc = bpy.context.scene
    sc.render.fps, sc.render.fps_base = FPS, 1.0  # o importador poe as chaves nos quadros deste ritmo
    new = scene.import_into_scene(path)
    try:
        arms = [o for o in new if o.type == "ARMATURE"]
        if not arms:
            raise ValueError("O arquivo não tem esqueleto. Baixe a animação do Mixamo em FBX.")
        arm = max(arms, key=lambda a: len(a.data.bones))
        action = arm.animation_data.action if arm.animation_data else None
        if action is None:
            raise ValueError("O arquivo tem esqueleto, mas não traz animação. No Mixamo, escolha a animação antes de baixar.")
        start, end = (int(round(v)) for v in action.frame_range)
        if end <= start:
            raise ValueError("A animação do arquivo tem um quadro só.")

        # Pai antes de filho, como o leitor de BVH entrega.
        bones: list = []
        stack = [b for b in arm.data.bones if b.parent is None][::-1]
        while stack:
            bone = stack.pop()
            bones.append(bone)
            stack.extend(reversed(bone.children))
        index = {b.name: i for i, b in enumerate(bones)}
        mapping, soma = rigmap.source_joint_names([(b.name, b.parent.name if b.parent else None) for b in bones])
        if not mapping["retargetable"]:
            faltam = ", ".join(rigmap.slot_label(s) if s != "torso" else "coluna" for s in mapping["missing_required"])
            raise ValueError(f"Não reconheci o esqueleto da animação como humanoide (faltam: {faltam}).")

        world = np.array(arm.matrix_world)
        world_rot = world[:3, :3] / np.linalg.norm(world[:3, :3], axis=0)
        to_src = SRC_TO_WORLD.T  # do mundo do Blender para os eixos do BVH do Kimodo
        rest_rot = [np.array(b.matrix_local)[:3, :3] for b in bones]
        rest_pos = np.array([to_src @ (world @ np.append(np.array(b.head_local), 1.0))[:3] for b in bones])

        n = end - start + 1
        grot = np.empty((n, len(bones), 3, 3))
        gpos = np.empty((n, len(bones), 3))
        for t in range(n):
            sc.frame_set(start + t)
            for j, bone in enumerate(bones):
                m = np.array(arm.pose.bones[bone.name].matrix)
                rot = m[:3, :3] / np.linalg.norm(m[:3, :3], axis=0)
                # Delta do descanso, em espaco de mundo, levado para os eixos da fonte.
                grot[t, j] = to_src @ world_rot @ rot @ rest_rot[j].T @ world_rot.T @ to_src.T
                gpos[t, j] = to_src @ (world @ m[:, 3])[:3]

        parents = np.array([index[b.parent.name] if b.parent else -1 for b in bones], dtype=np.int64)
        local_rot, local_pos, offsets = grot.copy(), gpos.copy(), rest_pos.copy()
        for j, p in enumerate(parents):
            if p >= 0:
                local_rot[:, j] = np.einsum("tji,tjk->tik", grot[:, p], grot[:, j])
                local_pos[:, j] = np.einsum("tji,tj->ti", grot[:, p], gpos[:, j] - gpos[:, p])
                offsets[j] = rest_pos[j] - rest_pos[p]
        motion = BvhMotion(
            names=rigmap.rename_to_soma([b.name for b in bones], soma),
            parents=parents,
            offsets=offsets,
            frame_time=1.0 / FPS,
            local_rot=local_rot,
            local_pos=local_pos,
        )
        # Altura do quadril em pe: o personagem do Mixamo fica com os pes no chao, na origem.
        motion.stand_height = float(rest_pos[index[mapping["slots"]["hips"]], 1])
        return motion
    finally:
        # O que veio no arquivo (esqueleto e, com "skin", a malha) nao pode ir para a previa.
        for obj in new:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
